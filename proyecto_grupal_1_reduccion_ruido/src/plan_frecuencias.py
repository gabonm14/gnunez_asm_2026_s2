#Plan de frecuencias del proyecto: verificación analítica y barrido de separación

import json

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks, get_window

if __package__ in (None, ''):
    from generacion import RAIZ, potencia, snr_db
    from analisis import guardar_csv, guardar_figura
    from filtrado_espectral import preparar_registro, memoria_base_bytes
else:
    from .generacion import RAIZ, potencia, snr_db
    from .analisis import guardar_csv, guardar_figura
    from .filtrado_espectral import preparar_registro, memoria_base_bytes

# Hann: los primeros ceros del lóbulo principal están en +-2 bins.
SEMIANCHO_HANN_BINS = 2


def cargar_configuraciones():
    nombres = ('configuraciones', 'filtro_temporal', 'filtro_espectral', 'plan_frecuencias', 'comparacion')
    return {n: json.loads((RAIZ / 'metadatos' / f'{n}.json').read_text(encoding='utf-8-sig'))
            for n in nombres}


def verificar_coherencia(cfg):
    """fs y N están repetidos en varios JSON; el plan solo vale si coinciden."""
    fs = cfg['configuraciones']['fs_hz']
    for nombre in ('filtro_temporal', 'filtro_espectral'):
        if cfg[nombre]['fs_hz'] != fs:
            raise ValueError(f'fs de {nombre}.json no coincide con configuraciones.json.')
    if cfg['filtro_espectral']['n_bloque'] != cfg['configuraciones']['n_bloque']:
        raise ValueError('n_bloque de filtro_espectral.json no coincide con configuraciones.json.')


# ancho completo del lóbulo principal de Hann: 4 bins = 4 fs/N
def separacion_teorica(N, fs):
    return 2 * SEMIANCHO_HANN_BINS * fs / N

# menor potencia de dos cuyo lóbulo de Hann cabe en la separación pedida
def n_minimo(separacion_hz, fs):
    return int(2 ** np.ceil(np.log2(2 * SEMIANCHO_HANN_BINS * fs / separacion_hz) - 1e-12))

# mayor potencia de dos cuyo buffer N/fs no supera la latencia pedida
def n_maximo(latencia_ms, fs):
    return int(2 ** np.floor(np.log2(latencia_ms * fs / 1000) + 1e-12))


# tonos útiles y ruido de cada caso como intervalos [f_min, f_max]
def componentes(config):
    filas = [{'origen': 'util', 'tipo': 'util', 'f_min_hz': f, 'f_max_hz': f}
             for f in config['frecuencias_utiles_hz']]
    for caso in config['casos']:
        # Solo casos con el multitono global: las distancias se miden a esos tonos útiles.
        if 'senal' in caso:
            continue
        if caso['tipo_ruido'] == 'tonal':
            f = caso['frecuencia_interferencia_hz']
            filas.append({'origen': caso['id'], 'tipo': 'interferencia_tonal', 'f_min_hz': f, 'f_max_hz': f})
        else:
            bajo, alto = caso['banda_ruido_hz']
            filas.append({'origen': caso['id'], 'tipo': 'ruido_banda', 'f_min_hz': bajo, 'f_max_hz': alto})
    return filas


def tabla_componentes(config, d_min):
    """Bin, margen a Nyquist y distancia a los tonos útiles de cada componente.

    En ruido de banda la distancia es 0 si algún tono útil cae dentro de la banda.
    zona='compromiso' significa que el ruido está a menos de d_min de un tono útil.
    """
    fs, N = config['fs_hz'], config['n_bloque']
    df = fs / N
    utiles = np.asarray(config['frecuencias_utiles_hz'], dtype=float)
    tabla = []
    for c in componentes(config):
        fila = {**c, 'bin_min': c['f_min_hz'] / df, 'bin_max': c['f_max_hz'] / df,
                'fraccion_bin': None, 'en_bin': None,
                'margen_nyquist_hz': fs / 2 - c['f_max_hz']}
        if c['f_min_hz'] == c['f_max_hz']:
            k = c['f_min_hz'] / df
            fila['fraccion_bin'] = float(k - np.round(k))
            fila['en_bin'] = bool(abs(fila['fraccion_bin']) < 1e-9)
        if c['tipo'] == 'util':
            otros = utiles[utiles != c['f_min_hz']]
            distancia = float(np.min(np.abs(otros - c['f_min_hz']))) if len(otros) else np.inf
        else:
            distancia = float(np.min(np.maximum(0, np.maximum(c['f_min_hz'] - utiles, utiles - c['f_max_hz']))))
        fila['distancia_util_hz'] = distancia
        fila['zona'] = 'resuelta' if distancia >= d_min else 'compromiso'
        tabla.append(fila)
    return tabla


def verificar_plan(config, plan, tabla):
    fs, N = config['fs_hz'], config['n_bloque']
    d_min = plan['separacion_minima_hz']
    if any(c['margen_nyquist_hz'] <= 0 for c in tabla):
        raise ValueError('Hay componentes en o sobre Nyquist: habría aliasing.')
    utiles = sorted(config['frecuencias_utiles_hz'])
    if len(utiles) > 1 and min(np.diff(utiles)) < d_min:
        raise ValueError('Dos tonos útiles están a menos de d_min: el sistema no puede separarlos.')
    if N < n_minimo(d_min, fs):
        raise ValueError(f'N={N} no resuelve d_min={d_min} Hz; se requiere N >= {n_minimo(d_min, fs)}.')
    if 1000 * N / fs > plan['latencia_buffer_max_ms']:
        raise ValueError(f'N={N} supera la latencia máxima; se requiere N <= {n_maximo(plan["latencia_buffer_max_ms"], fs)}.')
    avisos = []
    for c in tabla:
        if c['tipo'] == 'interferencia_tonal' and c['en_bin']:
            avisos.append(f"{c['origen']}: {c['f_min_hz']} Hz cae exacto en un bin; el resultado sobreestima un caso fuera de bin.")
        if c['tipo'] != 'util' and c['zona'] == 'compromiso':
            avisos.append(f"{c['origen']}: ruido a {c['distancia_util_hz']:.1f} Hz de un tono útil (< d_min); zona de compromiso.")
    return avisos


def mascara_por_picos(x, N, fs, utiles, prominencia_db, tolerancia_bins, mascaras=None):
    """WOLA Hann/Hann con salto N/2 que anula +-2 bins de cada pico no útil.

    Un pico a <= tolerancia_bins de un tono útil conocido se respeta.
    Con mascaras dadas las reutiliza para evaluar componentes (no es oráculo)."""
    extendida, inicios, pad = preparar_registro(x, N, N // 2)
    w = get_window('hann', N, fftbins=True)
    k = np.arange(N // 2 + 1)
    df = fs / N
    utiles = np.asarray(utiles, dtype=float)
    y = np.zeros_like(extendida)
    pesos = np.zeros_like(extendida)
    usadas = []
    for m, inicio in enumerate(inicios):
        X = np.fft.rfft(extendida[inicio:inicio + N] * w)
        if mascaras is None:
            G = np.ones(len(k))
            P = np.abs(X) ** 2
            # Piso relativo como en filtrado_espectral: evita log(0) y picos numéricos.
            db = 10 * np.log10(P + max(P.max() * 1e-12, np.finfo(float).tiny))
            picos, _ = find_peaks(db, prominence=prominencia_db)
            for p in picos:
                if np.min(np.abs(p * df - utiles)) > tolerancia_bins * df:
                    G[np.abs(k - p) <= SEMIANCHO_HANN_BINS] = 0.0
        else:
            G = mascaras[m]
        usadas.append(G)
        # Ganancia real 0/1: conserva la simetría conjugada.
        y[inicio:inicio + N] += np.fft.irfft(X * G, n=N) * w
        pesos[inicio:inicio + N] += w * w
    r = slice(pad, pad + len(x))
    return y[r] / pesos[r], usadas


def senal_util(config, t):
    return sum(a * np.sin(2 * np.pi * f * t + np.deg2rad(fase)) for f, a, fase in
               zip(config['frecuencias_utiles_hz'], config['amplitudes_utiles'], config['fases_utiles_grados']))


# Amplitud de una sinusoide (potencia A**2/2) que da la SNR pedida.
def amplitud_interferencia(s, snr_db_objetivo):
    return np.sqrt(2 * potencia(s) / 10 ** (snr_db_objetivo / 10))

# métricas con máscaras aprendidas de la mezcla y congeladas por componente
def evaluar_mascara(s, r, N, fs, utiles, barrido):
    x = s + r
    opciones = (barrido['prominencia_pico_db'], barrido['tolerancia_tono_util_bins'])
    y, M = mascara_por_picos(x, N, fs, utiles, *opciones)
    ys, _ = mascara_por_picos(s, N, fs, utiles, *opciones, mascaras=M)
    yr, _ = mascara_por_picos(r, N, fs, utiles, *opciones, mascaras=M)
    v = slice(N, len(s) - N)  # Excluye bordes del registro.
    return {'mejora_snr_db': snr_db(s[v], y[v]) - snr_db(s[v], x[v]),
            'energia_util_conservada_pct': float(100 * np.sum(ys[v] ** 2) / np.sum(s[v] ** 2)),
            'atenuacion_interferencia_db': float(10 * np.log10(
                np.sum(r[v] ** 2) / max(np.sum(yr[v] ** 2), np.finfo(float).tiny)))}


# Interferencia tonal a +-d Hz de cada tono útil, para cada N candidato y semilla
def barrido_separacion(cfg):
    config, plan = cfg['configuraciones'], cfg['plan_frecuencias']
    barrido = plan['barrido_separacion']
    criterios = cfg['comparacion']['criterios_predefinidos']
    fs = config['fs_hz']
    t = np.arange(int(barrido['duracion_s'] * fs)) / fs
    s = senal_util(config, t)
    amplitud = amplitud_interferencia(s, barrido['snr_entrada_db'])
    filas = []
    for N in plan['n_candidatos']:
        for tono in config['frecuencias_utiles_hz']:
            for d in barrido['separaciones_hz']:
                for signo in (-1, 1):
                    f = tono + signo * d
                    for semilla in barrido['semillas']:
                        fase = np.random.default_rng(semilla).uniform(-np.pi, np.pi)
                        r = amplitud * np.sin(2 * np.pi * f * t + fase)
                        m = evaluar_mascara(s, r, N, fs, config['frecuencias_utiles_hz'], barrido)
                        cumple = (m['mejora_snr_db'] >= criterios['mejora_min_casos_separados_db'] and
                                  m['energia_util_conservada_pct'] >= criterios['energia_util_min_casos_separados_pct'])
                        filas.append({'n_bloque': N, 'tono_util_hz': tono, 'separacion_hz': signo * d,
                                      'frecuencia_interferencia_hz': f, 'semilla': semilla, **m,
                                      'cumple': cumple})
    return filas

# menor |d| desde el cual TODAS las filas de ese N cumplen; None si ninguno
def separacion_medida(filas, N):
    propias = [f for f in filas if f['n_bloque'] == N]
    for d in sorted({abs(f['separacion_hz']) for f in propias}):
        if all(f['cumple'] for f in propias if abs(f['separacion_hz']) >= d):
            return d
    return None


def readaptacion(cfg, N):
    """Tiempo con error sobre el umbral cuando la interferencia salta de frecuencia.

    También devuelve el residuo estable antes y después del salto, en dB
    respecto a la potencia útil; un salto de dentro a fuera de bin lo cambia.
    """
    config, plan = cfg['configuraciones'], cfg['plan_frecuencias']
    p = plan['readaptacion']
    barrido = plan['barrido_separacion']
    fs = config['fs_hz']
    t = np.arange(int(p['duracion_s'] * fs)) / fs
    s = senal_util(config, t)
    f = np.where(t < p['instante_cambio_s'], p['frecuencia_inicial_hz'], p['frecuencia_final_hz'])
    # Fase acumulada: el salto de frecuencia no introduce una discontinuidad de fase.
    r = amplitud_interferencia(s, barrido['snr_entrada_db']) * np.sin(2 * np.pi * np.cumsum(f) / fs)
    y, _ = mascara_por_picos(s + r, N, fs, config['frecuencias_utiles_hz'],
                             barrido['prominencia_pico_db'], barrido['tolerancia_tono_util_bins'])
    v = max(1, int(p['ventana_envolvente_ms'] * fs / 1000))
    envolvente = np.convolve((y - s) ** 2, np.ones(v) / v, mode='same') / potencia(s)
    envolvente_db = 10 * np.log10(envolvente + np.finfo(float).tiny)
    n0 = int(p['instante_cambio_s'] * fs)
    interior = np.arange(N, len(t) - N)
    sobre = interior[envolvente_db[interior] > p['umbral_error_db']]
    return {'readaptacion_ms': 1000 * (sobre[-1] - sobre[0] + 1) / fs if len(sobre) else 0.0,
            'residuo_antes_db': float(np.median(envolvente_db[N:n0 - 2 * N])),
            'residuo_despues_db': float(np.median(envolvente_db[n0 + 2 * N:len(t) - N]))}


def figura_separacion(filas, criterios, ruta):
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.5))
    for N in sorted({f['n_bloque'] for f in filas}):
        propias = [f for f in filas if f['n_bloque'] == N]
        ds = sorted({abs(f['separacion_hz']) for f in propias})
        energia = [min(f['energia_util_conservada_pct'] for f in propias if abs(f['separacion_hz']) == d) for d in ds]
        mejora = [min(f['mejora_snr_db'] for f in propias if abs(f['separacion_hz']) == d) for d in ds]
        axs[0].plot(ds, energia, 'o-', label=f'N={N}')
        axs[1].plot(ds, mejora, 'o-', label=f'N={N}')
    axs[0].axhline(criterios['energia_util_min_casos_separados_pct'], color='gray', ls='--', label='Criterio')
    axs[1].axhline(criterios['mejora_min_casos_separados_db'], color='gray', ls='--', label='Criterio')
    axs[0].set(xlabel='Separación interferencia–tono útil (Hz)', ylabel='Energía útil conservada, peor caso (%)')
    axs[1].set(xlabel='Separación interferencia–tono útil (Hz)', ylabel='Mejora de SNR, peor caso (dB)')
    for ax in axs:
        ax.grid(True, alpha=.25)
        ax.legend()
    guardar_figura(fig, ruta)


def ejecutar_plan():
    cfg = cargar_configuraciones()
    verificar_coherencia(cfg)
    config, plan = cfg['configuraciones'], cfg['plan_frecuencias']
    criterios = cfg['comparacion']['criterios_predefinidos']
    fs, N = config['fs_hz'], config['n_bloque']
    d_min = plan['separacion_minima_hz']
    tabla = tabla_componentes(config, d_min)
    avisos = verificar_plan(config, plan, tabla)
    resultados = RAIZ / 'resultados'
    (resultados / 'figuras').mkdir(parents=True, exist_ok=True)
    filas = barrido_separacion(cfg)
    candidatos = []
    for n in plan['n_candidatos']:
        candidatos.append({'n_bloque': n, 'delta_f_hz': fs / n,
                           'separacion_teorica_hz': separacion_teorica(n, fs),
                           'separacion_medida_hz': separacion_medida(filas, n),
                           'latencia_buffer_ms': 1000 * n / fs, 'salto_ms': 1000 * (n // 2) / fs,
                           **readaptacion(cfg, n),
                           'memoria_base_bytes': memoria_base_bytes(n),
                           'cumple_resolucion': separacion_teorica(n, fs) <= d_min,
                           'cumple_latencia': 1000 * n / fs <= plan['latencia_buffer_max_ms']})
    if N in plan['n_candidatos']:
        medida = separacion_medida(filas, N)
        # el barrido usa un prototipo, no el método final del nodo 3.
        if medida is None or medida > d_min:
            desde = 'en ninguna separación barrida' if medida is None else f'desde {medida} Hz'
            avisos.append(f'Con N={N} el barrido cumple los criterios {desde}, no desde d_min={d_min} Hz.')
    guardar_csv(resultados / 'plan_frecuencias_candidatos.csv', candidatos)
    figura_separacion(filas, criterios, resultados / 'figuras' / 'plan_frecuencias_separacion.png')
    print(f'fs={fs} Hz, N={N}, Δf={fs / N:.3f} Hz, latencia de buffer {1000 * N / fs:.1f} ms')
    print(f'd_min={d_min} Hz -> N >= {n_minimo(d_min, fs)}; '
          f'latencia <= {plan["latencia_buffer_max_ms"]} ms -> N <= {n_maximo(plan["latencia_buffer_max_ms"], fs)}')
    for c in candidatos:
        print(f"N={c['n_bloque']}: separación teórica {c['separacion_teorica_hz']:.1f} Hz, "
              f"medida {c['separacion_medida_hz']} Hz, readaptación {c['readaptacion_ms']:.1f} ms, "
              f"residuo {c['residuo_antes_db']:.1f} -> {c['residuo_despues_db']:.1f} dB")
    for aviso in avisos:
        print('Aviso:', aviso)
    return candidatos


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ejecutar_plan()
