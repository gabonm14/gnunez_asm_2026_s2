"""Valida DC por bloque + Hann periódica + FFT del nodo 1 contra NumPy y la DFT directa.

    python nodo1/validacion/validar_fft.py --puerto /dev/ttyACM0   # esp-dsp en la placa
    python nodo1/validacion/validar_fft.py                         # radix-2 de PC (host)
    python nodo1/validacion/validar_fft.py --puerto COM3 --adc     # bloque real del micrófono

Error = max_k |X_nodo[k] - X_ref[k]| / max_k |X_ref[k]|; criterio de aceptación <= 1e-3.
La referencia se calcula en float64 a partir de las muestras crudas que imprime el nodo.
"""
import argparse
import json
import time

import numpy as np
from scipy.signal import get_window

from conexion import NODO1, Conexion
from src.analisis import dft_directa

CRITERIO = 1e-3


def validar(con, N, adc=False):
    con.comando(f'set n {N}')
    if adc:  # captura un momento y congela el último bloque (fuente nada) antes de pedirlo
        con.comando('fuente adc')
        time.sleep(0.5)
        con.comando('fuente nada')
    con.enviar(b'fft_prueba adc\n' if adc else b'fft_prueba\n')
    x = np.array(con.esperar('FFT_X')[1].split(), dtype=np.float64)
    y = np.array(con.esperar('FFT_OUT')[1].split(), dtype=np.float64)
    tiempos = dict(par.split('=') for par in con.esperar('OK')[1].split()[1:])
    X = y[0::2] + 1j * y[1::2]
    entrada = (x - x.mean()) * get_window('hann', N)  # periódica, como en src/analisis.py
    escala = np.abs(np.fft.fft(entrada)).max()
    error_fft = float(np.abs(X - np.fft.fft(entrada)).max() / escala)
    error_dft = float(np.abs(X - dft_directa(entrada)).max() / escala)
    return {'N': N, 'entrada': 'adc' if adc else 'sintetica', 'error_vs_numpy': error_fft, 'error_vs_dft_directa': error_dft,
            'cumple': error_fft <= CRITERIO and error_dft <= CRITERIO,
            **{k: (int(v) if v.isdigit() else v) for k, v in tiempos.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--puerto', help='puerto serie de la placa; sin él se usa host/nodo1_host')
    parser.add_argument('--n', type=int, nargs='+', default=[256, 512, 1024, 2048])
    parser.add_argument('--adc', action='store_true', help='usar bloques reales del ADC (requiere --puerto; N <= 1024)')
    args = parser.parse_args()
    if args.adc and not args.puerto:
        parser.error('--adc necesita la placa (--puerto)')
    con = Conexion(args.puerto)
    filas = [validar(con, N) for N in args.n]
    if args.adc:
        filas += [validar(con, N, adc=True) for N in args.n if N <= 1024]
    con.comando('set n 1024')
    con.cerrar()
    for f in filas:
        print(f"N={f['N']:5d} {f['entrada']:10s} error NumPy {f['error_vs_numpy']:.2e}  error DFT {f['error_vs_dft_directa']:.2e}  "
              f"fft {f.get('fft_us')} us  {'CUMPLE' if f['cumple'] else 'NO CUMPLE'} (<= {CRITERIO:g})")
    salida = NODO1 / 'resultados' / f"validacion_fft_{con.origen.split(':')[0]}.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps({'origen': con.origen, 'criterio': CRITERIO, 'resultados': filas}, indent=2),
                      encoding='utf-8')
    print(f'Guardado en {salida}')
    raise SystemExit(0 if all(f['cumple'] for f in filas) else 1)


if __name__ == '__main__':
    main()
