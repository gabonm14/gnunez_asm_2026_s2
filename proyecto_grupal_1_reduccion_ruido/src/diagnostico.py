"""Diagnóstico del nodo 1: estima tipo y frecuencias del ruido a partir de la mezcla.

Ejecutable con Run Python File en VS Code y con python -m src.diagnostico.
Usa SOLO la señal contaminada (nunca la limpia ni los metadatos del caso). El resultado
reemplaza la banda útil fija del nodo espectral cuando la confianza es alta; si el ruido
se superpone con la señal o la señal es de banda ancha, el espectro por sí solo no
permite separarlos y el diagnóstico lo declara (confianza baja) en vez de inventar una banda.
"""
import json
import time
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import get_window

if __package__ in (None, ''):
    from generacion import RAIZ, generar_caso, snr_db
    from analisis import guardar_csv, guardar_figura
    from filtrado_espectral import reducir_espectral
else:
    from .generacion import RAIZ, generar_caso, snr_db
    from .analisis import guardar_csv, guardar_figura
    from .filtrado_espectral import reducir_espectral


def cargar_config():
    return json.loads((RAIZ / 'metadatos/diagnostico.json').read_text(encoding='utf-8-sig'))


def psd_promediada(x, N):
    """Potencia por bin promediada sobre marcos Hann con 50 % de solapamiento.

    Equivale a promediar FFT de bloques consecutivos en el nodo 1 (media móvil de |X|^2).
    """
    x = np.asarray(x, dtype=np.float64)
    if N < 8 or N & (N - 1):
        raise ValueError('N debe ser potencia de dos, al menos 8.')
    if x.ndim != 1 or len(x) < N or not np.all(np.isfinite(x)):
        raise ValueError('Se requiere un vector real finito con al menos N muestras.')
    x = x - x.mean()
    w = get_window('hann', N)
    salto = N // 2
    marcos = 1 + (len(x) - N) // salto
    P = np.zeros(N // 2 + 1)
    for m in range(marcos):
        P += np.abs(np.fft.rfft(x[m * salto:m * salto + N] * w)) ** 2
    return P / marcos


def medir_impulsividad(x, fs, k_mad):
    """Curtosis en exceso y tasa de eventos atípicos de la primera diferencia.

    La diferencia realza los impulsos frente a tonos y bandas, que dan curtosis ~0 o
    negativa. Un evento es un grupo de muestras consecutivas sobre k_mad desviaciones.
    """
    x = np.asarray(x, dtype=np.float64)
    d = np.diff(x - x.mean())
    d = d - np.median(d)
    mad = np.median(np.abs(d)) / 0.6745
    m2 = np.mean(d ** 2)
    curtosis = float(np.mean(d ** 4) / m2 ** 2 - 3) if m2 > 0 else 0.0
    atipica = np.abs(d) > k_mad * max(mad, np.finfo(float).tiny)
    eventos = int(np.count_nonzero(atipica[1:] & ~atipica[:-1]) + atipica[0])
    return curtosis, eventos / (len(x) / fs)


def regiones_ocupadas(mascara, hueco):
    """Intervalos de bins [k0, k1] ocupados; se fusionan los separados por <= hueco bins."""
    idx = np.flatnonzero(mascara)
    if not len(idx):
        return []
    cortes = np.flatnonzero(np.diff(idx) > hueco + 1)
    return list(zip(np.r_[idx[0], idx[cortes + 1]].tolist(), np.r_[idx[cortes], idx[-1]].tolist()))


def describir_region(k0, k1, P, db, df, cfg):
    """Frecuencia del pico con interpolación parabólica sobre dB, ancho y potencia."""
    k = k0 + int(np.argmax(P[k0:k1 + 1]))
    delta = 0.0
    if 0 < k < len(P) - 1:
        a, b, c = db[k - 1], db[k], db[k + 1]
        if a - 2 * b + c < 0:
            delta = float(np.clip(0.5 * (a - c) / (a - 2 * b + c), -.5, .5))
    ancho = (k1 - k0 + 1) * df
    return {'f_lo_hz': k0 * df, 'f_hi_hz': k1 * df, 'f_pico_hz': (k + delta) * df, 'ancho_hz': ancho,
            'nivel_db': float(db[k]), 'potencia': float(P[k0:k1 + 1].sum()),
            'tipo': 'linea' if ancho <= cfg['ancho_linea_hz'] else 'banda'}


def picos_locales(P, db, rel, df, cfg):
    """Máximos locales (±2 bins) sobre el umbral de ocupación, como líneas de un bin.

    Los armónicos de 50/60 Hz están a ~3 bins entre sí: con el umbral de ocupación se
    fusionan en una sola región ancha, así que se buscan aparte como picos.
    """
    picos = []
    for k in range(2, len(P) - 2):
        if rel[k] > -cfg['umbral_ocupacion_db'] and P[k] == P[k - 2:k + 3].max() and P[k] > P[k - 1]:
            picos.append({**describir_region(k, k, P, db, df, cfg), 'k': k})
    return picos


def buscar_red(picos, cfg):
    """Familia 50/60 Hz: al menos armonicos_red_min armónicos distintos entre los picos."""
    mejor = None
    for f0 in cfg['frecuencias_red_hz']:
        coincide = {}
        for r in picos:
            k = int(round(r['f_pico_hz'] / f0))
            if 1 <= k <= cfg['max_armonico_red'] and abs(r['f_pico_hz'] - k * f0) <= cfg['tolerancia_red_hz']:
                coincide[k] = r
        if len(coincide) >= cfg['armonicos_red_min'] and (mejor is None or len(coincide) > len(mejor[1])):
            mejor = (f0, coincide)
    return mejor


def diagnosticar(x, fs, N, cfg):
    """Diagnóstico de la mezcla x (nada más que x)."""
    inicio = time.perf_counter()
    P = psd_promediada(x, N)
    df = fs / N
    db = 10 * np.log10(np.maximum(P, np.finfo(float).tiny))
    rel = db - db.max()
    mascara = rel > -cfg['umbral_ocupacion_db']
    mascara[:2] = False  # DC y su fuga: la media ya se eliminó.
    curtosis, tasa = medir_impulsividad(x, fs, cfg['k_atipicas_mad'])
    impulsivo = curtosis > cfg['umbral_curtosis']

    # Los armónicos de red se retiran de la máscara (con sus lóbulos) antes de formar regiones.
    red = buscar_red(picos_locales(P, db, rel, df, cfg), cfg)
    lineas_red = []
    if red:
        lineas_red = sorted(red[1].values(), key=lambda r: r['f_pico_hz'])
        for r in lineas_red:
            mascara[max(0, r['k'] - 4):r['k'] + 5] = False
    regiones = [describir_region(k0, k1, P, db, df, cfg)
                for k0, k1 in regiones_ocupadas(mascara, cfg['hueco_fusion_bins'])]
    restantes = sorted(regiones, key=lambda r: r['f_lo_hz'])

    # Bloque útil: desde la primera región, hasta el primer hueco >= hueco_util_hz.
    bloque = restantes[:1]
    for r in restantes[1:]:
        if r['f_lo_hz'] - bloque[-1]['f_hi_hz'] <= cfg['hueco_util_hz']:
            bloque.append(r)
        else:
            break
    interferencias = restantes[len(bloque):] + lineas_red
    if impulsivo:
        # Un piso plano de impulsos ocupa todo el espectro: no es una banda de ruido.
        casi_todo = .8 * fs / 2
        interferencias = [r for r in interferencias if r['ancho_hz'] < casi_todo]
        bloque = [r for r in bloque if r['ancho_hz'] < casi_todo]

    banda_ancha_util = any(r['tipo'] == 'banda' and r['f_lo_hz'] <= cfg['ancho_dc_hz'] for r in bloque)
    solapamiento = any(r['tipo'] == 'banda' and r['f_lo_hz'] > cfg['ancho_dc_hz'] for r in bloque)
    tipos = []
    if impulsivo:
        tipos.append('impulsivo')
    if lineas_red:
        tipos.append('red_electrica')
    if any(r['tipo'] == 'linea' for r in interferencias if not any(r is l for l in lineas_red)):
        tipos.append('tonal')
    if solapamiento or any(r['tipo'] == 'banda' for r in interferencias):
        tipos.append('banda')
    anchas = [r for r in interferencias + [b for b in bloque if b['tipo'] == 'banda' and b['f_lo_hz'] > cfg['ancho_dc_hz']]
              if r['tipo'] == 'banda']
    banda = max(anchas, key=lambda r: r['ancho_hz']) if anchas else None

    confiable = bool(bloque) and not solapamiento and not banda_ancha_util and not impulsivo
    p_util = sum(r['potencia'] for r in bloque)
    p_ruido = sum(r['potencia'] for r in interferencias)
    snr_est = float(10 * np.log10(p_util / p_ruido)) if confiable and p_ruido > 0 else None
    if confiable:
        motivo = 'bloque útil separado del ruido por un hueco espectral'
    elif impulsivo:
        motivo = 'ruido impulsivo: espectro plano, la banda útil no es observable'
    elif banda_ancha_util:
        motivo = 'señal de banda ancha desde DC: no se distingue del ruido de banda'
    elif solapamiento:
        motivo = 'ruido de banda superpuesto a la señal útil'
    else:
        motivo = 'no se encontró ninguna región ocupada'
    limpio = lambda r: {k: (float(v) if isinstance(v, (float, np.floating)) else v)
                        for k, v in r.items() if k != 'k'}
    # Sin tipos detectados: 'ninguno' solo si el espectro se pudo analizar con confianza.
    sin_tipo = 'ninguno' if confiable else 'indeterminado'
    return {'tipo': tipos[0] if len(tipos) == 1 else ('mixto' if tipos else sin_tipo),
            'tipos': tipos,
            'frecuencias_interferentes_hz': sorted(float(r['f_pico_hz']) for r in interferencias if r['tipo'] == 'linea'),
            'banda_ruido_hz': [float(banda['f_lo_hz']), float(banda['f_hi_hz'])] if banda else None,
            'frecuencia_red_hz': float(red[0]) if red else None,
            'fin_banda_util_hz': float(bloque[-1]['f_hi_hz'] + cfg['margen_banda_util_hz']) if confiable else None,
            'bloque_util_hz': [float(bloque[0]['f_lo_hz']), float(bloque[-1]['f_hi_hz'])] if bloque else None,
            'solapamiento': solapamiento, 'senal_banda_ancha': banda_ancha_util,
            'confianza': 'alta' if confiable else 'baja', 'motivo': motivo,
            'snr_estimada_db': snr_est, 'curtosis_diferencia': curtosis,
            'impulsos_por_s_estimados': float(tasa) if impulsivo else None,
            'regiones': [limpio(r) for r in regiones], 'interferencias': [limpio(r) for r in interferencias],
            'tiempo_calculo_ms': 1000 * (time.perf_counter() - inicio),
            '_espectro': (np.arange(len(P)) * df, rel)}


def adaptar_config_espectral(diag, base, fs):
    """Config del nodo 3 con la banda útil estimada; si la confianza es baja, la base.

    Mantiene el ancho de transición de la configuración base y respeta la restricción
    0 < fin_banda_util < inicio_rechazo < fs/2 de validar_config.
    """
    nueva = dict(base)
    if diag['confianza'] != 'alta' or diag['fin_banda_util_hz'] is None:
        return nueva, False
    fin = diag['fin_banda_util_hz']
    transicion = base['inicio_rechazo_hz'] - base['fin_banda_util_hz']
    if fin >= fs / 2 * .95:
        return nueva, False
    nueva['fin_banda_util_hz'] = fin
    nueva['inicio_rechazo_hz'] = min(fin + transicion, .5 * (fin + fs / 2))
    return nueva, True


def sin_espectro(diag):
    return {k: v for k, v in diag.items() if not k.startswith('_')}


def verdad_terreno(meta):
    """Etiqueta real del caso, usada SOLO para evaluar el diagnóstico."""
    if meta['tipo_ruido'] == 'tonal':
        return 'tonal', [meta['frecuencia_interferencia_hz']], None
    if meta['tipo_ruido'] == 'banda':
        return 'banda', [], meta['banda_ruido_hz']
    return 'impulsivo', [], None


def contaminar_red(config, f0, snr_objetivo, semilla, armonicos=5):
    """Señal útil + 50/60 Hz y armónicos (amplitud 1/k) a una SNR dada."""
    base = generar_caso(config, {'semilla': semilla, 'tipo_ruido': 'tonal',
                                 'frecuencia_interferencia_hz': f0, 'snr_objetivo_db': 100.0})
    t = base['tiempo']
    fases = np.random.default_rng(semilla).uniform(-np.pi, np.pi, armonicos)
    ruido = sum(np.sin(2 * np.pi * k * f0 * t + fases[k - 1]) / k for k in range(1, armonicos + 1))
    ruido *= np.sqrt(np.mean(base['limpia'] ** 2) / (np.mean(ruido ** 2) * 10 ** (snr_objetivo / 10)))
    return {**base, 'ruido': ruido, 'contaminada': base['limpia'] + ruido}


def evaluar_espectral(datos, config):
    s, x = datos['limpia'], datos['contaminada']
    y = reducir_espectral(x, config)['salida']
    N = config['n_bloque']
    v = slice(N, len(s) - N)
    return float(snr_db(s[v], y[v]) - snr_db(s[v], x[v]))


def barrido(config, cfg, N):
    """Aciertos y errores del diagnóstico sobre un barrido sintético controlado."""
    ex = cfg['experimento']
    config = {**config, 'duracion_s': ex['duracion_s']}
    casos = []
    for snr in ex['snr_db']:
        for semilla in ex['semillas']:
            for f in ex['frecuencias_tonales_hz']:
                casos.append(('tonal', snr, generar_caso(config, {'semilla': semilla, 'tipo_ruido': 'tonal',
                              'frecuencia_interferencia_hz': f, 'snr_objetivo_db': snr}), f, None))
            for banda in ex['bandas_hz']:
                casos.append(('banda', snr, generar_caso(config, {'semilla': semilla, 'tipo_ruido': 'banda',
                              'banda_ruido_hz': banda, 'snr_objetivo_db': snr}), None, banda))
            for tasa in ex['impulsos_por_s']:
                casos.append(('impulsivo', snr, generar_caso(config, {'semilla': semilla, 'tipo_ruido': 'impulsivo',
                              'impulsos_por_s': tasa, 'snr_objetivo_db': snr}), tasa, None))
            for f0 in ex['frecuencias_red_hz']:
                casos.append(('red_electrica', snr, contaminar_red(config, f0, snr, semilla), f0, None))
    filas = []
    for tipo, snr, datos, ref, banda in casos:
        d = diagnosticar(datos['contaminada'], config['fs_hz'], N, cfg)
        fila = {'tipo_real': tipo, 'snr_real_db': snr, 'referencia': str(ref if ref is not None else banda),
                'tipo_detectado': d['tipo'],
                'acierto_tipo': int(tipo in d['tipos']), 'exclusivo': int(d['tipo'] == tipo),
                'confianza': d['confianza'], 'error_freq_hz': '', 'error_borde_banda_hz': '',
                'error_snr_estimada_db': '', 'error_tasa_impulsos': ''}
        if tipo == 'tonal' and d['frecuencias_interferentes_hz']:
            fila['error_freq_hz'] = float(min(abs(f - ref) for f in d['frecuencias_interferentes_hz']))
        if tipo == 'red_electrica' and d['frecuencia_red_hz'] is not None:
            fila['error_freq_hz'] = abs(d['frecuencia_red_hz'] - ref)
        if tipo == 'banda' and d['banda_ruido_hz']:
            fila['error_borde_banda_hz'] = float(max(abs(d['banda_ruido_hz'][0] - banda[0]),
                                                      abs(d['banda_ruido_hz'][1] - banda[1])))
        if tipo == 'impulsivo' and d['impulsos_por_s_estimados'] is not None:
            fila['error_tasa_impulsos'] = abs(d['impulsos_por_s_estimados'] - ref) / ref
        if d['snr_estimada_db'] is not None and tipo != 'banda':
            fila['error_snr_estimada_db'] = d['snr_estimada_db'] - snr
        filas.append(fila)
    return filas


def resumen_barrido(filas):
    resumen = []
    for tipo in dict.fromkeys(f['tipo_real'] for f in filas):
        for snr in sorted({f['snr_real_db'] for f in filas if f['tipo_real'] == tipo}):
            sel = [f for f in filas if f['tipo_real'] == tipo and f['snr_real_db'] == snr]
            num = lambda clave: [f[clave] for f in sel if f[clave] != '']
            media = lambda v: float(np.mean(v)) if v else ''
            resumen.append({'tipo_real': tipo, 'snr_real_db': snr, 'pruebas': len(sel),
                            'acierto_tipo_pct': 100 * float(np.mean([f['acierto_tipo'] for f in sel])),
                            'solo_ese_tipo_pct': 100 * float(np.mean([f['exclusivo'] for f in sel])),
                            'confianza_alta_pct': 100 * float(np.mean([f['confianza'] == 'alta' for f in sel])),
                            'error_freq_medio_hz': media(num('error_freq_hz')),
                            'error_freq_max_hz': float(max(num('error_freq_hz'))) if num('error_freq_hz') else '',
                            'error_borde_banda_medio_hz': media(num('error_borde_banda_hz')),
                            'error_tasa_impulsos_medio': media(num('error_tasa_impulsos')),
                            'error_snr_estimada_medio_db': media(num('error_snr_estimada_db'))})
    return resumen


def figura_espectros(resultados, base, ruta):
    fig, axs = plt.subplots(3, 3, figsize=(16, 11))
    for ax, (nombre, diag) in zip(axs.ravel(), resultados.items()):
        f, rel = diag['_espectro']
        ax.plot(f, rel, lw=.8)
        for r in diag['regiones']:
            ax.axvspan(r['f_lo_hz'], r['f_hi_hz'], color='tab:orange', alpha=.3)
        if diag['fin_banda_util_hz']:
            ax.axvline(diag['fin_banda_util_hz'], color='tab:green', label='Fin de banda útil estimado')
        ax.axvline(base['fin_banda_util_hz'], color='gray', ls='--', label='Banda útil fija (base)')
        ax.set(title=f"{nombre}: {diag['tipo']} ({diag['confianza']})", ylim=(-90, 3))
        ax.set_xlabel('Frecuencia (Hz)')
        ax.set_ylabel('dB re máximo')
        ax.grid(True, alpha=.25)
    axs[0, 0].legend(fontsize=7, loc='lower right')
    for ax in axs.ravel()[len(resultados):]:
        ax.axis('off')
    guardar_figura(fig, ruta)


def ejecutar_diagnostico(casos=None):
    cfg = cargar_config()
    config = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))
    base = json.loads((RAIZ / 'metadatos/filtro_espectral.json').read_text(encoding='utf-8-sig'))
    fs, N = config['fs_hz'], base['n_bloque']
    # generar_caso no escribe en disco: no se tocan los archivos de pruebas/.
    casos = {c['id']: generar_caso(config, c) for c in config['casos']} if casos is None else casos
    resultados = RAIZ / 'resultados'
    filas, diags = [], {}
    for nombre, datos in casos.items():
        d = diagnosticar(datos['contaminada'], fs, N, cfg)  # solo la mezcla
        diags[nombre] = d
        tipo, frecuencias, banda = verdad_terreno(datos['metadatos'])
        nueva, usa = adaptar_config_espectral(d, base, fs)
        fila = {'caso': nombre, 'tipo_real': tipo, 'tipo_detectado': d['tipo'], 'confianza': d['confianza'],
                'motivo': d['motivo'],
                'frecuencia_real_hz': frecuencias[0] if frecuencias else '',
                'frecuencia_estimada_hz': d['frecuencias_interferentes_hz'][0] if d['frecuencias_interferentes_hz'] else '',
                'banda_real_hz': str(banda) if banda else '',
                'banda_estimada_hz': str([round(v) for v in d['banda_ruido_hz']]) if d['banda_ruido_hz'] else '',
                'fin_banda_util_estimado_hz': d['fin_banda_util_hz'] if d['fin_banda_util_hz'] else '',
                'snr_real_db': datos['metadatos']['snr_obtenida_db'],
                'snr_estimada_db': d['snr_estimada_db'] if d['snr_estimada_db'] is not None else '',
                'impulsos_real_por_s': datos['metadatos'].get('impulsos_por_s', ''),
                'impulsos_estimados_por_s': d['impulsos_por_s_estimados'] if d['impulsos_por_s_estimados'] else '',
                'usa_diagnostico': int(usa),
                'mejora_snr_base_db': evaluar_espectral(datos, base),
                'mejora_snr_diagnostico_db': evaluar_espectral(datos, nueva) if usa else '',
                'tiempo_diagnostico_ms': d['tiempo_calculo_ms']}
        filas.append(fila)
    guardar_csv(resultados / 'diagnostico_casos.csv', filas)

    # Escenarios tipo P6: señal útil que NO cae en la banda fija de 1500 Hz.
    ex = cfg['experimento']
    p6 = []
    for esc in ex['escenarios_p6']:
        conf = {**config, 'duracion_s': ex['duracion_s'], **{k: esc[k] for k in
                ('frecuencias_utiles_hz', 'amplitudes_utiles', 'fases_utiles_grados')}}
        caso = {k: v for k, v in esc.items() if k in ('tipo_ruido', 'frecuencia_interferencia_hz', 'banda_ruido_hz')}
        datos = generar_caso(conf, {**caso, 'semilla': ex['semillas'][0], 'snr_objetivo_db': 5.0})
        d = diagnosticar(datos['contaminada'], fs, N, cfg)
        nueva, usa = adaptar_config_espectral(d, base, fs)
        p6.append({'escenario': esc['nombre'], 'tipo_detectado': d['tipo'], 'confianza': d['confianza'],
                   'fin_banda_util_estimado_hz': d['fin_banda_util_hz'] or '',
                   'mejora_snr_base_db': evaluar_espectral(datos, base),
                   'mejora_snr_diagnostico_db': evaluar_espectral(datos, nueva) if usa else ''})
    guardar_csv(resultados / 'diagnostico_p6.csv', p6)

    filas_barrido = barrido(config, cfg, N)
    resumen = resumen_barrido(filas_barrido)
    guardar_csv(resultados / 'diagnostico_barrido.csv', resumen)
    figura_espectros(diags, base, resultados / 'figuras' / 'diagnostico_espectros.png')
    (resultados / 'diagnostico_resumen.json').write_text(json.dumps(
        {'parametros': cfg, 'n_bloque': N, 'casos': {k: sin_espectro(v) for k, v in diags.items()}},
        indent=2), encoding='utf-8')
    for f in filas:
        print(f"{f['caso']}: real {f['tipo_real']} -> {f['tipo_detectado']} ({f['confianza']}); "
              f"banda útil fin {f['fin_banda_util_estimado_hz']}; mejora base {f['mejora_snr_base_db']:.2f} dB"
              + (f", diagnóstico {f['mejora_snr_diagnostico_db']:.2f} dB" if f['usa_diagnostico'] else ''))
    for p in p6:
        print(f"P6 {p['escenario']}: {p['tipo_detectado']} ({p['confianza']}); mejora base "
              f"{p['mejora_snr_base_db']:.2f} dB, diagnóstico {p['mejora_snr_diagnostico_db']}")
    for r in resumen:
        print(f"barrido {r['tipo_real']} SNR {r['snr_real_db']} dB: tipo {r['acierto_tipo_pct']:.0f} %, "
              f"solo ese tipo {r['solo_ese_tipo_pct']:.0f} %, error freq {r['error_freq_medio_hz']}")
    return {'casos': diags, 'filas': filas, 'p6': p6, 'barrido': resumen}


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ejecutar_diagnostico()
