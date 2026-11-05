"""Verifica la captura del nodo 1 con espectros por componente (Welch), sin alinear en el tiempo.

Cuatro capturas de capturar.py, misma prueba, distancia y ganancia, con el emisor en:
  --sala    0 (silencio)        --limpia  comp limpia
  --ruido   comp ruido          --mezcla  comp mezcla
Cada captura incluye una vez el ruido de la sala, así que debe cumplirse, banda por banda,
    P_mezcla ≈ P_limpia + P_ruido − P_sala.
Además: SNR real en el micrófono, peso de la sala, picos de la limpia y del ruido, bandas de la
mezcla que no están en la limpia ni en el ruido (armónicos o intermodulación: la cadena no es
lineal) y Parseval por bloque (energía en el tiempo = energía en frecuencia, con la misma ventana).
El nivel de la mezcla debe quedar en el rango lineal del ADC (máx. 2450 mV, mín. 150 mV): por
encima el ESP32 comprime la señal sin llegar a 4095, y eso no cuenta como recorte.
Detalle en docs/nodo1_verificacion.md, "Método de verificación".

    python nodo1/validacion/verificar_espectros.py --sala nodo1/capturas/p1_sala.npz \\
        --limpia nodo1/capturas/p1_limpia.npz --ruido nodo1/capturas/p1_ruido.npz \\
        --mezcla nodo1/capturas/p1_mezcla.npz --tonos 440 --tonos-ruido 2508 --nombre p1

Sin --sala se supone una sala en silencio (P_sala = 0), como en las capturas simuladas.
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from analizar_captura import DF, FS, N, cargar, medir_tonos, psd_db, tramo_continuo
from conexion import NODO1
from src.diagnostico import psd_promediada

ANCHO_BANDA_HZ = 250
F_MIN_HZ, F_MAX_HZ = 2 * DF, 7500   # sin DC ni el borde del anti-aliasing
TOL_SUMA_DB = 1.0                   # el estimador de Welch de 10 s varía ≈ 0.1 dB por banda de 250 Hz
TOL_PARSEVAL = 1e-6                 # identidad exacta salvo redondeo
NUEVA_DB = 3                        # banda de la mezcla 3 dB sobre limpia + ruido − sala
RANGO_MV = (150, 2450)              # rango lineal del ADC con atenuación de 12 dB
SIGNIFICATIVA = 10                  # banda que sobresale 10 dB del piso de la sala


def potencias(ruta):
    x = tramo_continuo(cargar(ruta))
    return x, psd_promediada(x, N)


def bandas(P):
    """Potencia por banda de ANCHO_BANDA_HZ entre F_MIN_HZ y F_MAX_HZ."""
    k = np.arange(len(P)) * DF
    bordes = np.arange(F_MIN_HZ, F_MAX_HZ, ANCHO_BANDA_HZ)
    return bordes, np.array([P[(k >= a) & (k < a + ANCHO_BANDA_HZ)].sum() for a in bordes])


def parseval(x):
    """Σ (x·w)² = Σ|X|²/N en cada bloque de N con la ventana de Hann, sumado sobre los bloques.

    Es la escala con que se suman las potencias por banda. (Comparar la potencia media de toda la
    señal con la suma de la PSD de Welch no es exacto con señales que cambian en el tiempo, como
    la canción o el chirp: Hann² con 50 % de solapamiento no pesa igual todas las muestras.)
    """
    w = np.hanning(N + 1)[:-1]
    marcos = (x[:len(x) // N * N] - x.mean()).reshape(-1, N) * w
    tiempo = float(np.sum(marcos ** 2))
    frecuencia = float(np.sum(np.abs(np.fft.fft(marcos, axis=1)) ** 2) / N)
    return tiempo, frecuencia, abs(frecuencia / tiempo - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sala', type=Path)
    parser.add_argument('--limpia', type=Path, required=True)
    parser.add_argument('--ruido', type=Path, required=True)
    parser.add_argument('--mezcla', type=Path, required=True)
    parser.add_argument('--tonos', type=float, nargs='*', default=[], help='tonos útiles esperados en la limpia')
    parser.add_argument('--tonos-ruido', type=float, nargs='*', default=[], help='tonos esperados en el ruido')
    parser.add_argument('--nombre', default='espectros')
    args = parser.parse_args()

    (xl, Pl), (xr, Pr), (xm, Pm) = (potencias(r) for r in (args.limpia, args.ruido, args.mezcla))
    Ps = potencias(args.sala)[1] if args.sala else np.zeros_like(Pl)
    bordes, (Bl, Br, Bm, Bs) = bandas(Pl)[0], [bandas(P)[1] for P in (Pl, Pr, Pm, Ps)]
    esperado = Bl + Br - Bs
    piso = Bs if args.sala else np.full_like(Bs, esperado.max() * 1e-4)
    validas = esperado > SIGNIFICATIVA * piso
    desvio = 10 * np.log10(Bm[validas] / esperado[validas])

    # Bandas con contenido en la mezcla que no viene de la limpia ni del ruido: no linealidad.
    nuevas = (Bm > SIGNIFICATIVA * Bs) & (Bm > 10 ** (NUEVA_DB / 10) * np.maximum(esperado, Bs))
    util, ruido = np.clip(Bl - Bs, 0, None).sum(), np.clip(Br - Bs, 0, None).sum()
    nivel = json.loads(str(cargar(args.mezcla)['estado_adc'])) or {}  # vacío en capturas simuladas
    r = {'archivos': {k: str(getattr(args, k)) for k in ('sala', 'limpia', 'ruido', 'mezcla')},
         'bandas_comparadas': int(validas.sum()), 'ancho_banda_hz': ANCHO_BANDA_HZ,
         'desvio_suma_max_db': float(np.max(np.abs(desvio))) if validas.any() else float('nan'),
         'desvio_suma_mediana_db': float(np.median(desvio)) if validas.any() else float('nan'),
         'snr_microfono_db': float(10 * np.log10(util / ruido)) if util > 0 and ruido > 0 else float('nan'),
         'bandas_nuevas_hz': [[float(a), float(a + ANCHO_BANDA_HZ), float(10 * np.log10(Bm[i] / max(esperado[i], Bs[i])))]
                              for i, a in enumerate(bordes) if nuevas[i]],
         'mezcla_min_mv': nivel.get('min_mv'), 'mezcla_max_mv': nivel.get('max_mv')}
    if args.sala:
        r['sala_bajo_limpia_db'] = float(10 * np.log10(Bl.sum() / Bs.sum()))
        r['sala_bajo_ruido_db'] = float(10 * np.log10(Br.sum() / Bs.sum()))
    f, db_l = psd_db(xl)
    r['tonos_limpia'] = medir_tonos(f, db_l, args.tonos) if args.tonos else []
    r['tonos_ruido'] = medir_tonos(*psd_db(xr), args.tonos_ruido) if args.tonos_ruido else []
    t, fr, err = parseval(xm)
    r['parseval'] = {'potencia_tiempo': t, 'potencia_frecuencia': fr, 'error_relativo': err}
    r['criterios'] = {f'mezcla_=_limpia_+_ruido_-_sala_(<=_{TOL_SUMA_DB}_dB)': bool(validas.any())
                      and r['desvio_suma_max_db'] <= TOL_SUMA_DB,
                      'sin_bandas_nuevas_en_la_mezcla': not nuevas.any(),
                      f'mezcla_en_rango_lineal_del_adc_({RANGO_MV[0]}-{RANGO_MV[1]}_mV)':
                          not nivel or RANGO_MV[0] <= nivel['min_mv'] and nivel['max_mv'] <= RANGO_MV[1],
                      'picos_a_<=_1_bin': all(x['dentro_de_1_bin'] for x in r['tonos_limpia'] + r['tonos_ruido']),
                      'parseval_por_bloque': err <= TOL_PARSEVAL}

    print(f"Bandas de {ANCHO_BANDA_HZ} Hz comparadas: {r['bandas_comparadas']}; mezcla frente a limpia + ruido − sala: "
          f"máximo {r['desvio_suma_max_db']:.2f} dB, mediana {r['desvio_suma_mediana_db']:+.2f} dB")
    print(f"SNR real en el micrófono: {r['snr_microfono_db']:.2f} dB")
    print(f"Mezcla en el ADC: {r['mezcla_min_mv']} a {r['mezcla_max_mv']} mV (lineal: {RANGO_MV[0]} a {RANGO_MV[1]})")
    for a, b, d in r['bandas_nuevas_hz']:
        print(f"   banda nueva en la mezcla: {a:.0f}-{b:.0f} Hz, {d:+.1f} dB sobre limpia + ruido")
    if args.sala:
        print(f"Sala: {r['sala_bajo_limpia_db']:.1f} dB bajo la limpia, {r['sala_bajo_ruido_db']:.1f} dB bajo el ruido")
    for nombre in ('tonos_limpia', 'tonos_ruido'):
        for x in r[nombre]:
            print(f"   {nombre}: {x['tono_hz']:.0f} Hz -> {x['pico_hz']:.1f} Hz (error {x['error_hz']:.2f} Hz)")
    print(f"Parseval por bloque: error relativo {err:.1e}")
    print('Criterios: ' + ', '.join(f"{k} {'sí' if v else 'NO'}" for k, v in r['criterios'].items()))

    salida = NODO1 / 'resultados'
    salida.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    a_db = lambda P: 10 * np.log10(np.maximum(P, 1e-12))
    k = np.arange(len(Pl)) * DF
    for P, etiqueta in ((Pl, 'limpia'), (Pr, 'ruido'), (Pm, 'mezcla')) + (((Ps, 'sala'),) if args.sala else ()):
        ax.plot(k, a_db(P), lw=.8, label=etiqueta)
    ax.plot(k, a_db(np.clip(Pl + Pr - Ps, 1e-12, None)), 'k--', lw=.8, label='limpia + ruido − sala')
    ax.set(xlabel='Frecuencia (Hz)', ylabel='dB (códigos²)', title=f'Espectros por componente: {args.nombre}',
           xlim=(0, FS / 2))
    ax.grid(True, alpha=.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(salida / f'espectros_{args.nombre}.png', dpi=150)
    (salida / f'espectros_{args.nombre}.json').write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Guardado en {salida}/espectros_{args.nombre}.png y .json')
    raise SystemExit(0 if all(r['criterios'].values()) else 1)


if __name__ == '__main__':
    main()
