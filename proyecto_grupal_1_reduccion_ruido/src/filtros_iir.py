"""IIR causal pasa bajas en secciones de segundo orden y comparación contra el FIR.

Ejecutable con Run Python File en VS Code y con python -m src.filtros_iir.
Usa la MISMA especificación del FIR (metadatos/filtro_temporal.json); solo los
parámetros propios del IIR están en metadatos/filtro_iir.json. El diseño es de
SciPy (buttord/cheb1ord); el procesamiento propio usa biquads en forma directa II
transpuesta, conserva estado entre bloques y no usa lfilter ni sosfilt.
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import (buttord, butter, cheb1ord, cheby1, sosfilt, sosfreqz,
                          sos2zpk, firwin, freqz)

if __package__ in (None, ''):
    from generacion import RAIZ, generar_todos, snr_db
    from analisis import guardar_csv, guardar_figura
    from filtros_temporales import disenar_fir, filtrar_por_bloques
else:
    from .generacion import RAIZ, generar_todos, snr_db
    from .analisis import guardar_csv, guardar_figura
    from .filtros_temporales import disenar_fir, filtrar_por_bloques

FAMILIAS = {'butterworth': 'Butterworth', 'chebyshev1': 'Chebyshev tipo I'}


def cargar_specs():
    """Especificación común con el FIR más parámetros propios del IIR."""
    spec = json.loads((RAIZ / 'metadatos/filtro_temporal.json').read_text(encoding='utf-8-sig'))
    cfg = json.loads((RAIZ / 'metadatos/filtro_iir.json').read_text(encoding='utf-8-sig'))
    return spec, cfg


def medir_respuesta_sos(sos, spec):
    """Mismas medidas que medir_respuesta del FIR, sobre una malla densa."""
    f, H = sosfreqz(sos, worN=65536, fs=spec['fs_hz'])
    paso_db = 20 * np.log10(np.maximum(abs(H[f <= spec['paso_hz']]), 1e-15))
    rechazo = float(-20 * np.log10(max(abs(H[f >= spec['rechazo_hz']]))))
    return {'rizado_pico_a_pico_db': float(np.ptp(paso_db)),
            'desviacion_paso_max_db': float(max(abs(paso_db))),
            'atenuacion_rechazo_min_db': rechazo}


def normalizar_secciones(sos):
    """Reparte la ganancia para que cada biquad tenga ganancia DC unitaria.

    SciPy concentra toda la ganancia en la primera sección (b ~ 1e-7, que en
    punto fijo se redondea a cero) y deja b = [1, 2, 1], que no cabe en Q2.14.
    La respuesta total no cambia; la ganancia residual (p. ej. -rizado en un
    Chebyshev de orden par) se asigna a la primera sección.
    """
    sos = np.array(sos, dtype=float)
    dc = sos[:, :3].sum(axis=1) / sos[:, 3:].sum(axis=1)
    sos[:, :3] /= dc[:, None]
    sos[0, :3] *= np.prod(dc)
    return sos


def disenar_iir(spec, cfg, familia):
    """Orden mínimo analítico (buttord/cheb1ord) en secciones de segundo orden.

    gpass se reduce y gstop se aumenta con un margen para que la verificación
    numérica sobre malla densa cumpla la especificación original.
    """
    fs = spec['fs_hz']
    if not 0 < spec['paso_hz'] < spec['rechazo_hz'] < fs / 2:
        raise ValueError('Debe cumplirse 0 < paso < rechazo < fs/2.')
    gpass = spec['rizado_max_db'] * cfg['margen_rizado']
    gstop = spec['atenuacion_min_db'] + cfg['margen_atenuacion_db']
    args = (spec['paso_hz'], spec['rechazo_hz'], gpass, gstop)
    if familia == 'butterworth':
        orden, wn = buttord(*args, fs=fs)
        sos = butter(orden, wn, btype='low', output='sos', fs=fs)
    elif familia == 'chebyshev1':
        orden, wn = cheb1ord(*args, fs=fs)
        sos = cheby1(orden, gpass, wn, btype='low', output='sos', fs=fs)
    else:
        raise ValueError(f'Familia desconocida: {familia}')
    sos = normalizar_secciones(sos)
    medida = medir_respuesta_sos(sos, spec)
    if (medida['rizado_pico_a_pico_db'] > spec['rizado_max_db'] or
            medida['atenuacion_rechazo_min_db'] < spec['atenuacion_min_db']):
        raise RuntimeError(f'{familia}: el diseño no cumple la especificación.')
    z, p, k = sos2zpk(sos)
    radio = float(max(abs(p)))
    return sos, {**medida, 'familia': familia, 'orden': int(orden), 'secciones': len(sos),
                 'frecuencia_natural_hz': float(np.atleast_1d(wn)[0]),
                 'gpass_diseno_db': gpass, 'gstop_diseno_db': gstop,
                 'radio_polo_max': radio, 'margen_estabilidad': 1 - radio,
                 'estable_bibo': bool(radio < 1), 'roc_causal': f'|z| > {radio:.6f}'}


class SOSCausal:
    """Cascada de biquads en forma directa II transpuesta.

    Cada sección: y = b0 x + z1; z1 = b1 x - a1 y + z2; z2 = b2 x - a2 y.
    El mismo objeto debe procesar todos los bloques consecutivos: reiniciarlo
    en cada bloque crearía transitorios artificiales.
    """
    def __init__(self, sos, dtype=np.float64):
        self.sos = np.asarray(sos, dtype=dtype).copy()
        if self.sos.ndim != 2 or self.sos.shape[1] != 6 or not np.all(np.isfinite(self.sos)):
            raise ValueError('sos debe ser una matriz finita de N x 6.')
        if not np.allclose(self.sos[:, 3], 1):
            raise ValueError('Cada sección debe estar normalizada con a0 = 1.')
        self.estado = np.zeros((len(self.sos), 2), dtype=dtype)
        self.dtype = dtype

    def procesar(self, bloque):
        x = np.asarray(bloque, dtype=self.dtype)
        if x.ndim != 1 or not np.all(np.isfinite(x)):
            raise ValueError('El bloque debe ser un vector finito.')
        y = np.empty_like(x)
        for n, muestra in enumerate(x):
            v = muestra
            for s, (b0, b1, b2, _, a1, a2) in enumerate(self.sos):
                salida = b0 * v + self.estado[s, 0]
                self.estado[s, 0] = b1 * v - a1 * salida + self.estado[s, 1]
                self.estado[s, 1] = b2 * v - a2 * salida
                v = salida
            y[n] = v
        return y


def filtrar_sos_por_bloques(x, sos, n_bloque=1024, dtype=np.float64):
    if not isinstance(n_bloque, int) or n_bloque <= 0:
        raise ValueError('El tamaño del bloque debe ser positivo.')
    filtro = SOSCausal(sos, dtype=dtype)
    x = np.asarray(x)
    salida = np.empty(len(x), dtype=dtype)
    for inicio in range(0, len(x), n_bloque):
        salida[inicio:inicio + n_bloque] = filtro.procesar(x[inicio:inicio + n_bloque])
    return salida


def cuantizar_coef(sos, bits_fraccion):
    """Q2.14 por defecto: rango [-2, 2) porque |a1| puede acercarse a 2.

    Solo cuantiza coeficientes (no simula aritmética fija). Devuelve la matriz
    y cuántos coeficientes se saturaron.
    """
    escala = 2 ** bits_fraccion
    q = np.rint(sos * escala)
    saturados = int(np.count_nonzero((q > 32767) | (q < -32768)))
    return np.clip(q, -32768, 32767) / escala, saturados


def retardo_grupo(sos, fs, n=16384):
    f, H = sosfreqz(sos, worN=n, fs=fs)
    fase = np.unwrap(np.angle(H))
    omega = 2 * np.pi * f / fs
    tau = -np.gradient(fase, omega)
    tau[abs(H) < 1e-3] = np.nan  # No interpretable en rechazo profundo.
    return f, H, tau


def muestras_asentamiento(sos, umbral, largo=1 << 16):
    """Muestras tras las cuales |h[n]| queda bajo umbral*max|h| (transitorio)."""
    impulso = np.zeros(largo)
    impulso[0] = 1
    h = sosfilt(sos, impulso)
    activos = np.nonzero(abs(h) > umbral * max(abs(h)))[0]
    return int(activos[-1]) + 1


def retardo_efectivo(s, ys, inicio, lag_max):
    """Retardo entero que mejor alinea la limpia filtrada con la limpia.

    El IIR tiene fase no lineal: no existe un retardo único. Se toma el que
    minimiza el error sobre la señal limpia (sin ruido), como retardo efectivo.
    """
    L = len(s)
    errores = [np.mean((s[inicio:L - lag] - ys[inicio + lag:L]) ** 2) for lag in range(lag_max + 1)]
    return int(np.argmin(errores))


def evaluar_salida(s, x, ruido, y, ys, yr, inicio, lag):
    """Métricas del FIR (temporal_metricas.csv) con el mismo intervalo alineado."""
    L = len(s)
    ref, ent, sal = s[inicio:L - lag], x[inicio:L - lag], y[inicio + lag:L]
    snr_in, snr_out = snr_db(ref, ent), snr_db(ref, sal)
    # Independiente del retardo: por linealidad y = ys + yr, así que la relación
    # útil/ruido a la salida no depende de cómo se alinee con la referencia.
    snr_sep = float(10 * np.log10(np.sum(ys[inicio:] ** 2) / np.sum(yr[inicio:] ** 2)))
    return {'snr_entrada_db': snr_in, 'snr_salida_alineada_db': snr_out,
            'mejora_snr_alineada_db': snr_out - snr_in,
            'snr_salida_separada_db': snr_sep,
            'mejora_snr_separada_db': snr_sep - snr_in,
            'mse_alineado': float(np.mean((ref - sal) ** 2)),
            'retardo_muestras': lag, 'inicio_referencia': inicio,
            'energia_util_conservada_pct': float(100 * np.sum(ys[inicio + lag:L] ** 2) / np.sum(ref ** 2)),
            'atenuacion_ruido_total_db': float(10 * np.log10(np.sum(ruido[inicio:L - lag] ** 2) /
                                                              np.sum(yr[inicio + lag:L] ** 2))),
            'pico_salida': float(max(abs(y)))}


def figura_respuesta(disenos, b_fir, spec, ruta):
    """Magnitud, zoom de banda de paso y retardo de grupo: FIR vs IIR."""
    fs = spec['fs_hz']
    fig, axs = plt.subplots(3, 1, figsize=(11, 10))
    curvas = []
    f, H = freqz(b_fir, worN=16384, fs=fs)
    omega = 2 * np.pi * f / fs
    tau = -np.gradient(np.unwrap(np.angle(H)), omega)
    curvas.append((f'FIR (orden {len(b_fir) - 1})', f, H, tau))
    for familia, (sos, res) in disenos.items():
        f, H, tau = retardo_grupo(sos, fs)
        curvas.append((f'{FAMILIAS[familia]} (orden {res["orden"]})', f, H, tau))
    for etiqueta, f, H, tau in curvas:
        axs[0].plot(f, 20 * np.log10(np.maximum(abs(H), 1e-12)), label=etiqueta)
        axs[1].plot(f, 20 * np.log10(np.maximum(abs(H), 1e-12)), label=etiqueta)
        axs[2].plot(f, tau, label=etiqueta)
    axs[0].axhline(-spec['atenuacion_min_db'], color='tab:red', ls='--', label='Rechazo requerido')
    axs[0].set(ylabel='Ganancia (dB)', ylim=(-120, 5), title='Respuesta en frecuencia: FIR contra IIR')
    axs[1].set(ylabel='Ganancia (dB)', xlim=(0, spec['paso_hz'] * 1.1),
               ylim=(-1.5 * spec['rizado_max_db'], 1.5 * spec['rizado_max_db']), title='Zoom en banda de paso')
    axs[2].set(ylabel='Retardo de grupo (muestras)', xlim=(0, spec['rechazo_hz'] * 1.2), title='Retardo de grupo')
    for ax in axs:
        ax.axvspan(spec['paso_hz'], spec['rechazo_hz'], color='gray', alpha=.15)
        ax.set_xlabel('Frecuencia (Hz)')
        ax.grid(True, alpha=.25)
        ax.legend(fontsize=8)
    guardar_figura(fig, ruta)


def figura_polos_ceros(disenos, ruta):
    fig, axs = plt.subplots(1, len(disenos), figsize=(7 * len(disenos), 7))
    axs = np.atleast_1d(axs)
    angulo = np.linspace(0, 2 * np.pi, 500)
    for ax, (familia, (sos, res)) in zip(axs, disenos.items()):
        z, p, _ = sos2zpk(sos)
        ax.plot(np.cos(angulo), np.sin(angulo), '--', color='gray', label='Círculo unitario')
        ax.add_patch(plt.Circle((0, 0), res['radio_polo_max'], fill=False, color='tab:red', alpha=.4,
                                label='Borde de la ROC'))
        ax.scatter(z.real, z.imag, facecolors='none', edgecolors='tab:blue', label=f'Ceros ({len(z)})')
        ax.scatter(p.real, p.imag, marker='x', c='tab:red', label=f'Polos ({len(p)})')
        ax.annotate(f'ROC causal: {res["roc_causal"]}\nEstable: el círculo unitario está en la ROC',
                    (.03, .03), xycoords='axes fraction')
        ax.set(xlabel='Parte real', ylabel='Parte imaginaria',
               title=f'{FAMILIAS[familia]}: orden {res["orden"]}, {res["secciones"]} secciones')
        ax.set_aspect('equal')
        ax.grid(True, alpha=.25)
        ax.legend(loc='upper right', fontsize=8)
    guardar_figura(fig, ruta)


def tabla_secciones(sos):
    """Una fila por biquad con sus coeficientes, ceros y polos."""
    filas = []
    for i, (b0, b1, b2, a0, a1, a2) in enumerate(sos):
        z, p, _ = sos2zpk(sos[i:i + 1])
        _, H = sosfreqz(sos[i:i + 1], worN=8192)
        filas.append({'seccion': i + 1, 'b0': b0, 'b1': b1, 'b2': b2, 'a1': a1, 'a2': a2,
                      'polo_radio': float(max(abs(p))),
                      'ganancia_pico_seccion_db': float(20 * np.log10(max(abs(H))))})
    return filas


def costo(sos, n_bloque):
    s = len(sos)
    return {'multiplicaciones_por_muestra': 5 * s, 'sumas_por_muestra': 4 * s,
            'ram_coef_estado_float32_bytes': 4 * (5 * s + 2 * s),
            'ram_buffer_entrada_salida_float32_bytes': 8 * n_bloque}


def ejecutar_iir(casos=None):
    spec, cfg = cargar_specs()
    b_fir, res_fir = disenar_fir(spec)
    casos = generar_todos() if casos is None else casos
    resultados = RAIZ / 'resultados'
    figuras = resultados / 'figuras'
    figuras.mkdir(parents=True, exist_ok=True)
    disenos = {fam: disenar_iir(spec, cfg, fam) for fam in cfg['familias']}
    figura_respuesta(disenos, b_fir, spec, figuras / 'iir_respuesta.png')
    figura_polos_ceros(disenos, figuras / 'iir_polos_ceros.png')

    prueba = np.random.default_rng(7).uniform(-.5, .5, 8192)
    cuantizacion = []
    for familia, (sos, res) in disenos.items():
        referencia = filtrar_sos_por_bloques(prueba, sos)
        sos_q, saturados = cuantizar_coef(sos, cfg['bits_fraccion_coef'])
        variantes = [('float64', sos, np.float64, 0),
                     ('float32_coef_y_estado', sos.astype(np.float32), np.float32, 0),
                     (f'coef_Q2.{cfg["bits_fraccion_coef"]}', sos_q, np.float64, saturados)]
        for formato, coef, dtype, sat in variantes:
            coef64 = np.asarray(coef, dtype=np.float64)
            y = filtrar_sos_por_bloques(prueba, coef64, dtype=dtype)
            radio = float(max(abs(sos2zpk(coef64)[1])))
            cuantizacion.append({'familia': familia, 'formato': formato,
                                 'error_coef_max': float(np.max(abs(coef64 - sos))),
                                 'coef_saturados': sat, 'radio_polo_max': radio,
                                 'estable': bool(radio < 1),
                                 'error_salida_max_vs_float64': float(np.max(abs(y - referencia))),
                                 **medir_respuesta_sos(coef64, spec)})
    guardar_csv(resultados / 'iir_cuantizacion.csv', cuantizacion)

    filas, salidas = [], {}
    asentamiento = {fam: muestras_asentamiento(sos, cfg['umbral_asentamiento']) for fam, (sos, _) in disenos.items()}
    for nombre, datos in casos.items():
        if datos['metadatos']['fs_hz'] != spec['fs_hz']:
            raise ValueError('El filtro y la señal deben usar la misma fs.')
        x, s, ruido = datos['contaminada'], datos['limpia'], datos['ruido']
        N = datos['metadatos']['n_bloque']
        M, D = res_fir['orden'], res_fir['retardo_muestras']
        yf = filtrar_por_bloques(x, b_fir, N)
        filas.append({'caso': nombre, 'filtro': f'FIR_orden_{M}', 'familia': 'fir',
                      'error_vs_biblioteca_max': 0.0,
                      **evaluar_salida(s, x, ruido, yf, filtrar_por_bloques(s, b_fir, N),
                                       filtrar_por_bloques(ruido, b_fir, N), M, D)})
        for familia, (sos, res) in disenos.items():
            y = filtrar_sos_por_bloques(x, sos, N)
            referencia = sosfilt(sos, x)
            error = float(max(abs(y - referencia)))
            if not np.allclose(y, referencia, atol=cfg['tolerancia_atol'], rtol=cfg['tolerancia_rtol']):
                raise AssertionError(f'{familia}: la implementación propia no coincide con sosfilt.')
            ys = filtrar_sos_por_bloques(s, sos, N)
            yr = filtrar_sos_por_bloques(ruido, sos, N)
            inicio = asentamiento[familia]
            # Se busca solo hasta el retardo de grupo máximo de la banda de paso:
            # más allá, un tono alinea por periodicidad y no por retardo real.
            f_g, _, tau = retardo_grupo(sos, spec['fs_hz'])
            lag_max = int(np.ceil(np.nanmax(tau[f_g <= spec['paso_hz']])))
            if len(s) <= inicio + lag_max:
                raise ValueError('Registro demasiado corto para la evaluación alineada.')
            lag = retardo_efectivo(s, ys, inicio, lag_max)
            filas.append({'caso': nombre, 'filtro': f'{familia}_orden_{res["orden"]}', 'familia': familia,
                          'error_vs_biblioteca_max': error,
                          **evaluar_salida(s, x, ruido, y, ys, yr, inicio, lag)})
            salidas[(nombre, familia)] = y
    guardar_csv(resultados / 'iir_metricas.csv', filas)

    n_bloque = next(iter(casos.values()))['metadatos']['n_bloque']
    comparativa = [{'filtro': f'FIR orden {len(b_fir) - 1}', 'orden': len(b_fir) - 1,
                    'multiplicaciones_por_muestra': len(b_fir), 'sumas_por_muestra': len(b_fir) - 1,
                    'ram_coef_estado_float32_bytes': 4 * (2 * len(b_fir) - 1),
                    'retardo_grupo_muestras': D, 'fase': 'lineal',
                    'rizado_pico_a_pico_db': res_fir['rizado_pico_a_pico_db'],
                    'atenuacion_rechazo_min_db': res_fir['atenuacion_rechazo_min_db']}]
    for familia, (sos, res) in disenos.items():
        f, _, tau = retardo_grupo(sos, spec['fs_hz'])
        paso = f <= spec['paso_hz']
        comparativa.append({'filtro': f'{FAMILIAS[familia]} orden {res["orden"]}', 'orden': res['orden'],
                            **{k: v for k, v in costo(sos, n_bloque).items() if k != 'ram_buffer_entrada_salida_float32_bytes'},
                            'retardo_grupo_muestras': float(np.nanmean(tau[paso])),
                            'fase': f'no lineal (retardo {np.nanmin(tau[paso]):.1f} a {np.nanmax(tau[paso]):.1f})',
                            'rizado_pico_a_pico_db': res['rizado_pico_a_pico_db'],
                            'atenuacion_rechazo_min_db': res['atenuacion_rechazo_min_db']})
    guardar_csv(resultados / 'iir_vs_fir.csv', comparativa)

    detalle = {'especificacion': spec, 'parametros_iir': cfg, 'disenos': {}}
    for familia, (sos, res) in disenos.items():
        z, p, _ = sos2zpk(sos)
        detalle['disenos'][familia] = {
            **res, 'sos': sos.tolist(), 'secciones_detalle': tabla_secciones(sos),
            'H_z': 'prod_{i=1}^{%d} (b0_i + b1_i z^-1 + b2_i z^-2) / (1 + a1_i z^-1 + a2_i z^-2)' % len(sos),
            'polos': [{'real': float(v.real), 'imag': float(v.imag)} for v in p],
            'ceros': [{'real': float(v.real), 'imag': float(v.imag)} for v in z],
            'muestras_asentamiento': asentamiento[familia], **costo(sos, n_bloque),
            'nota_cuantizacion': 'Q2.14 cuantiza coeficientes; acumulación fija y saturación quedan por validar en hardware.'}
    (resultados / 'iir_diseno.json').write_text(json.dumps(detalle, indent=2), encoding='utf-8')

    for familia, (sos, res) in disenos.items():
        print(f"{FAMILIAS[familia]}: orden {res['orden']}, {res['secciones']} secciones, "
              f"radio polo máx {res['radio_polo_max']:.6f}, rizado {res['rizado_pico_a_pico_db']:.4f} dB, "
              f"rechazo {res['atenuacion_rechazo_min_db']:.2f} dB")
    for fila in filas:
        print(f"{fila['caso']} {fila['filtro']}: mejora SNR alineada={fila['mejora_snr_alineada_db']:.3f} dB; "
              f"separada={fila['mejora_snr_separada_db']:.3f} dB; retardo={fila['retardo_muestras']} muestras")
    return {'disenos': disenos, 'metricas': filas, 'salidas': salidas, 'comparativa': comparativa}


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ejecutar_iir()
