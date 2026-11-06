"""Analiza capturas del nodo 1 (archivos de capturar.py) frente a los criterios de aceptación.

Por cada captura:
  - integridad: bloques perdidos, recortes, atrasos, duración y fs (por marcas de tiempo y por la PC);
  - nivel: DC, pico y RMS en códigos del ADC, para ajustar la ganancia del micrófono;
  - diagnóstico: cada diagnóstico que viajó en las tramas se repite con diagnosticar() de
    Python sobre las MISMAS muestras (las tramas dicen qué muestras cubrió) y se comparan;
  - espectro: PSD promediada; con --tonos, nivel y error de ubicación de cada pico;
  - con --caso, el espectro digital del caso y la respuesta relativa del canal en los tonos;
  - con --limpia, alineación por correlación con una captura de la señal limpia y SNR en el micrófono.
Con varias capturas (repeticiones) se reporta media y desviación de las métricas.

    python nodo1/validacion/analizar_captura.py nodo1/capturas/caso_1_r*.npz --caso caso_1 \\
        --tonos 440 880 1320 2500
    python nodo1/validacion/analizar_captura.py nodo1/capturas/piso_r*.npz   # emisor en reposo
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from conexion import NODO1, RAIZ
from src.diagnostico import cargar_config, diagnosticar, psd_promediada

FS, N = 16000, 1024
DF = FS / N
ESCALA = 2048           # 1.0 de la señal normalizada = 2048 códigos del ADC
DURACION_MINIMA_S = 10
TOL_LINEA_HZ = 1.0
TOL_SNR_DB = 0.5


def cargar(ruta):
    d = np.load(ruta, allow_pickle=False)
    return {k: d[k] for k in d.files} | {'diags': json.loads(str(d['diags'])), 'nota': str(d['nota'])}


def integridad(c):
    seq, n = c['seq'], int(c['n_bloque'])
    t = c['t_us'].astype(np.int64)
    t = np.concatenate([[0], np.cumsum(np.diff(t) % 2 ** 32)])  # desenrolla el contador de 32 bits
    fs_marcas = (seq[-1] - seq[0]) * n / (t[-1] / 1e6) if t[-1] > 0 else float('nan')
    t_pc = c['t_pc']
    fs_pc = (seq[-1] - seq[0]) * n / (t_pc[-1] - t_pc[0]) if t_pc[-1] > t_pc[0] else float('nan')
    return {'bloques': int(len(seq)), 'bloques_perdidos': int(seq[-1] - seq[0] + 1 - len(seq)),
            'muestras_recortadas': int(c['recortadas'].sum()), 'muestras_atrasadas': int(c['atrasadas'].sum()),
            'duracion_s': len(c['muestras']) / FS, 'fs_marcas_tiempo_hz': float(fs_marcas),
            'fs_reloj_pc_hz': float(fs_pc), 'fs_firmware_hz': float(c['fs_medida_hz'][-1])}


def nivel(c):
    x = c['muestras'][c['valido']].astype(float)
    return {'dc_codigo': float(np.median(c['dc_codigo'])), 'pico_codigos': float(np.abs(x).max()),
            'rms_codigos': float(np.sqrt(np.mean(x ** 2))),
            'rms_dbfs': float(20 * np.log10(max(np.sqrt(np.mean(x ** 2)), 1e-9) / ESCALA))}


def comparar_diagnosticos(c, cfg):
    """Repite en Python cada diagnóstico del firmware sobre las mismas muestras."""
    filas = []
    base = int(c['seq0']) * int(c['n_bloque'])
    for d in c['diags']:
        fin = d['diag_fin_muestra'] - base
        ini = fin - d['diag_muestras']
        if ini < 0 or fin > len(c['muestras']) or not c['valido'][ini:fin].all():
            continue  # el periodo empezó antes de la captura o cruza un bloque perdido
        p = diagnosticar(c['muestras'][ini:fin].astype(np.float64) / ESCALA, FS, d['n_fft'], cfg)
        lineas_p = p['frecuencias_interferentes_hz'][:4]
        nan_igual = lambda a, b: (a is None or np.isnan(a)) and (b is None or np.isnan(b))
        cerca = lambda a, b, tol: nan_igual(a, b) or (a is not None and b is not None and abs(a - b) <= tol)
        fila = {'diag': d['diag_numero'], 'tipos_python': p['tipos'], 'tipos_nodo': d['tipos'],
                'confianza_python': p['confianza'], 'confianza_nodo': 'alta' if d['confianza_alta'] else 'baja',
                'fin_banda_util_python': p['fin_banda_util_hz'], 'fin_banda_util_nodo': d['fin_banda_util_hz'],
                'lineas_python': lineas_p, 'lineas_nodo': d['lineas_hz']}
        fila['coincide'] = bool(
            set(p['tipos']) == set(d['tipos']) and fila['confianza_python'] == fila['confianza_nodo']
            and cerca(p['fin_banda_util_hz'], d['fin_banda_util_hz'], DF)
            and len(lineas_p) == len(d['lineas_hz'])
            and all(abs(a - b) <= TOL_LINEA_HZ for a, b in zip(lineas_p, d['lineas_hz']))
            and all(cerca(a, b, DF) for a, b in zip(p['banda_ruido_hz'] or [None, None], d['banda_ruido_hz']))
            and cerca(p['frecuencia_red_hz'], d['frecuencia_red_hz'], 0)
            and cerca(p['snr_estimada_db'], d['snr_estimada_db'], TOL_SNR_DB))
        filas.append(fila)
    return filas


def tramo_continuo(c):
    """El tramo más largo sin bloques perdidos (para la PSD)."""
    v = np.r_[False, c['valido'], False].astype(int)
    ini, fin = np.flatnonzero(np.diff(v) == 1), np.flatnonzero(np.diff(v) == -1)
    k = int(np.argmax(fin - ini))
    return c['muestras'][ini[k]:fin[k]].astype(np.float64)


def medir_tonos(f, db, tonos):
    """Pico en ±3 bins de cada tono, con interpolación parabólica; nivel en dB re fondo de escala."""
    filas = []
    for f0 in tonos:
        k0 = int(round(f0 / DF))
        k = k0 - 3 + int(np.argmax(db[k0 - 3:k0 + 4]))
        a, b, cc = db[k - 1:k + 2]
        delta = 0.5 * (a - cc) / (a - 2 * b + cc) if a - 2 * b + cc < 0 else 0.0
        filas.append({'tono_hz': f0, 'pico_hz': float((k + delta) * DF), 'error_hz': float(abs((k + delta) * DF - f0)),
                      'dentro_de_1_bin': bool(abs((k + delta) * DF - f0) <= DF), 'nivel_db': float(b)})
    return filas


def psd_db(x):
    """PSD promediada en dB re una senoidal de fondo de escala (2048 códigos de pico)."""
    P = psd_promediada(x, N)
    ref = (ESCALA / 2 * np.sum(np.hanning(N + 1)[:-1])) ** 2  # |X|^2 de un seno de pico ESCALA en su bin
    return np.arange(len(P)) * DF, 10 * np.log10(np.maximum(P, 1e-30) / ref)


def alinear(limpia, x):
    """Retardo por correlación cruzada, ganancia por mínimos cuadrados y SNR en el micrófono."""
    m = len(limpia) + len(x)
    r = np.fft.irfft(np.fft.rfft(x, m) * np.conj(np.fft.rfft(limpia, m)), m)
    lag = int(np.argmax(np.abs(r)))
    lag = lag - m if lag > m // 2 else lag
    a, b = (limpia[:len(limpia) - lag], x[lag:]) if lag >= 0 else (limpia[-lag:], x)
    L = min(len(a), len(b))
    a, b = a[:L], b[:L]
    g = float(a @ b / (a @ a))
    e = b - g * a
    return {'retardo_muestras': lag, 'retardo_ms': 1000 * lag / FS, 'ganancia': g,
            'snr_microfono_db': float(10 * np.log10((g * g * (a @ a)) / (e @ e)))}


def analizar(ruta, cfg, tonos, caso, limpia):
    c = cargar(ruta)
    r = {'archivo': str(ruta), 'nota': c['nota'], **integridad(c), **nivel(c)}
    r['diagnosticos'] = comparar_diagnosticos(c, cfg)
    x = tramo_continuo(c)
    f, db = psd_db(x)
    r['tonos'] = medir_tonos(f, db, tonos) if tonos else []
    if caso and tonos:  # respuesta relativa del canal: nivel capturado - nivel digital, sin la ganancia media
        xd = np.load(RAIZ / 'pruebas' / caso / 'muestras.npz')['contaminada'] * ESCALA
        dig = medir_tonos(*psd_db(xd), tonos)
        dif = np.array([a['nivel_db'] - b['nivel_db'] for a, b in zip(r['tonos'], dig)])
        for t, d in zip(r['tonos'], dif - np.median(dif)):
            t['canal_relativo_db'] = float(d)
    if limpia:
        r['alineacion'] = alinear(tramo_continuo(cargar(limpia)), x)
    bandas = ((20, 500), (500, 2000), (2000, 5000), (5000, 8000))
    r['potencia_bandas_dbfs'] = {f'{a}-{b} Hz': float(10 * np.log10(np.sum(10 ** (db[(f >= a) & (f < b)] / 10))))
                                 for a, b in bandas}
    r['criterios'] = {'sin_recorte': r['muestras_recortadas'] == 0, 'sin_bloques_perdidos': r['bloques_perdidos'] == 0,
                      f'duracion_>=_{DURACION_MINIMA_S}_s': r['duracion_s'] >= DURACION_MINIMA_S,
                      'picos_a_<=_1_bin': all(t['dentro_de_1_bin'] for t in r['tonos']),
                      'diagnostico_igual_a_python': all(d['coincide'] for d in r['diagnosticos'])}
    return r, (f, db)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capturas', nargs='+', type=Path)
    parser.add_argument('--tonos', type=float, nargs='*', default=[])
    parser.add_argument('--caso', help='caso de pruebas/ que reprodujo el emisor (espectro digital de referencia)')
    parser.add_argument('--limpia', type=Path, help='captura de la señal limpia por el mismo canal')
    parser.add_argument('--nombre', help='nombre de los archivos de salida (por defecto, el de la primera captura)')
    args = parser.parse_args()
    cfg = cargar_config()
    resultados, espectros = zip(*(analizar(r, cfg, args.tonos, args.caso, args.limpia) for r in args.capturas))

    for r in resultados:
        coinciden = sum(d['coincide'] for d in r['diagnosticos'])
        print(f"{Path(r['archivo']).name}: {r['duracion_s']:.1f} s, perdidos {r['bloques_perdidos']}, "
              f"recortes {r['muestras_recortadas']}, fs PC {r['fs_reloj_pc_hz']:.1f} Hz, "
              f"pico {r['pico_codigos']:.0f} códigos, RMS {r['rms_dbfs']:.1f} dBFS, "
              f"diagnósticos iguales a Python {coinciden}/{len(r['diagnosticos'])}")
        for t in r['tonos']:
            print(f"   tono {t['tono_hz']:.0f} Hz -> pico {t['pico_hz']:.1f} Hz (error {t['error_hz']:.2f} Hz), "
                  f"{t['nivel_db']:.1f} dBFS" + (f", canal {t['canal_relativo_db']:+.1f} dB" if 'canal_relativo_db' in t else ''))
        if 'alineacion' in r:
            a = r['alineacion']
            print(f"   retardo {a['retardo_ms']:.2f} ms, SNR en el micrófono {a['snr_microfono_db']:.1f} dB")
        print('   criterios: ' + ', '.join(f"{k} {'sí' if v else 'NO'}" for k, v in r['criterios'].items()))

    resumen = {}
    if len(resultados) > 1:  # repeticiones: media y desviación estándar
        metricas = ['rms_dbfs', 'pico_codigos', 'fs_reloj_pc_hz'] + [f'tono_{t:.0f}_db' for t in args.tonos]
        for m in metricas:
            v = [r[m] if m in r else next(t['nivel_db'] for t in r['tonos'] if f"tono_{t['tono_hz']:.0f}_db" == m)
                 for r in resultados]
            resumen[m] = {'media': float(np.nanmean(v)), 'desviacion': float(np.nanstd(v, ddof=1))}
            print(f"{m}: {resumen[m]['media']:.2f} ± {resumen[m]['desviacion']:.2f} (n={len(v)})")

    nombre = args.nombre or args.capturas[0].stem
    salida = NODO1 / 'resultados'
    salida.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for r, (f, db) in zip(resultados, espectros):
        ax.plot(f, db, lw=.8, label=Path(r['archivo']).stem)
    if args.caso:
        f, db = psd_db(np.load(RAIZ / 'pruebas' / args.caso / 'muestras.npz')['contaminada'] * ESCALA)
        ax.plot(f, db - np.max(db) + max(np.max(e[1]) for e in espectros), 'k--', lw=.8,
                label=f'{args.caso} digital (alineado al máximo)')
    ax.set(xlabel='Frecuencia (Hz)', ylabel='dB re fondo de escala', title=f'Espectro capturado: {nombre}',
           xlim=(0, FS / 2))
    ax.grid(True, alpha=.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(salida / f'captura_{nombre}.png', dpi=150)
    (salida / f'captura_{nombre}.json').write_text(
        json.dumps({'capturas': resultados, 'repeticiones': resumen}, indent=2, ensure_ascii=False, default=float),
        encoding='utf-8')
    print(f'Guardado en {salida}/captura_{nombre}.png y .json')


if __name__ == '__main__':
    main()
