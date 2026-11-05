"""Verifica la referencia limpia del nodo 1 (docs/nodo1_verificacion.md, "Referencia limpia para el MSE").

1) Sin --captura: corre "prueba_ref" en el firmware (el ejecutable de PC, o la placa con
   --puerto): señal conocida, pulsos de 2 ms para guardar la referencia y de 1 ms con la mezcla.
2) Con --captura: una captura de capturar.py hecha con la referencia ya guardada
   ("ref capturar" con el emisor en comp limpia). Compara las muestras con la referencia que
   viajó en las mismas tramas: MSE, SNR, y lo mismo con la referencia corrida ±1 muestra.
   - Emisor en comp limpia: el error es casi solo el ruido de la sala (techo de la SNR medible).
   - Emisor en comp mezcla: la SNR es la de entrada; compárela con verificar_espectros.py.
   - Corrida ±1 muestra, el MSE debe subir: confirma que la alineación es la correcta.

    python nodo1/validacion/verificar_referencia.py
    python nodo1/validacion/verificar_referencia.py --captura nodo1/capturas/p1_mezcla.npz
"""
import argparse
import json

import numpy as np

from analizar_captura import ESCALA, cargar
from conexion import Conexion
from trama import REF_SIN


def prueba_firmware(puerto):
    con = Conexion(puerto)
    _, resto = con.comando('prueba_ref')
    con.cerrar()
    r = json.loads(resto.split(' ', 1)[1])
    print(f"prueba_ref ({con.origen}): {'CUMPLE' if r['cumple'] else 'NO CUMPLE'}")
    for k, v in r.items():
        print(f'   {k}: {v}')
    return r['cumple']


def metricas(x, s):
    e = x - s
    return {'mse_codigos2': float(np.mean(e ** 2)), 'mse_normalizado': float(np.mean(e ** 2) / ESCALA ** 2),
            'snr_db': float(10 * np.log10(np.sum(s ** 2) / np.sum(e ** 2)))}


def verificar_captura(ruta):
    c = cargar(ruta)
    x, ref = c['muestras'].astype(float), c['referencia'].astype(float)
    vale = (c['referencia'] != REF_SIN) & c['valido']
    if vale.sum() < 16000:
        raise SystemExit(f'Solo {int(vale.sum())} muestras con referencia: guarde la referencia ("ref capturar") '
                         'con el emisor en comp limpia antes de capturar.')
    r = {'muestras_con_referencia': int(vale.sum()), 'alineada': metricas(x[vale], ref[vale])}
    for d in (-1, 1):  # misma comparación con la referencia corrida una muestra
        i = np.flatnonzero(vale)
        i = i[(i + d >= 0) & (i + d < len(x))]
        i = i[vale[i + d]]
        r[f'corrida_{d:+d}'] = metricas(x[i], ref[i + d])
    sube = all(r[f'corrida_{d:+d}']['mse_codigos2'] > r['alineada']['mse_codigos2'] for d in (-1, 1))
    print(f"{ruta}: {r['muestras_con_referencia']} muestras con referencia")
    for k in ('alineada', 'corrida_-1', 'corrida_+1'):
        m = r[k]
        print(f"   {k:11s} MSE {m['mse_codigos2']:.1f} códigos² ({m['mse_normalizado']:.3g}), SNR {m['snr_db']:.2f} dB")
    print(f"   corrida ±1 muestra sube el MSE: {'sí' if sube else 'NO'}")
    return sube


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--puerto', help='consola USB de la placa; sin él se usa el ejecutable de PC')
    parser.add_argument('--captura', help='captura .npz con referencia')
    args = parser.parse_args()
    ok = verificar_captura(args.captura) if args.captura else prueba_firmware(args.puerto)
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
