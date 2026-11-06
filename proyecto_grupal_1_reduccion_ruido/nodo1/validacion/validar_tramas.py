"""Prueba de recepción de tramas con bloques conocidos.

1) Consola (host o --puerto): el firmware arma k tramas con el patrón conocido y las imprime
   en hexadecimal (las impares con referencia); aquí se decodifican con trama.Receptor
   (implementación independiente) y se verifican CRC, secuencia, muestras y referencia. Luego se inyectan fallas en ese flujo (bit alterado,
   trama perdida, basura) y se comprueba que se detecten. También corre prueba_trama, la
   misma verificación hecha por el receptor del firmware, y se comprueba que los parámetros
   del diagnóstico de caso_1 lleguen en la trama igual que en el DIAG.
2) --uart PUERTO: tramas reales de GPIO17 leídas con un adaptador USB-UART (GND común).
   Con --puerto además se pone la placa en "fuente patron" y se verifican las muestras.
   La fs se estima contra el reloj de la PC, que es independiente del cristal del ESP32.

    python nodo1/validacion/validar_tramas.py
    python nodo1/validacion/validar_tramas.py --puerto COM3 --uart COM4 --segundos 60
"""
import argparse
import json
import time

import numpy as np

from conexion import NODO1, RAIZ, Conexion, parametros_proyecto
from trama import Receptor, es_patron

K = 20


def prueba_consola(con):
    _, resto = con.comando('prueba_trama')
    firmware = json.loads(resto.split(' ', 1)[1])
    con.enviar(f'tramas_conocidas {K}\n'.encode())
    flujo = []
    while True:
        etiqueta, resto = con.esperar('TRAMA', 'OK')
        if etiqueta == 'OK':
            break
        flujo.append(bytes.fromhex(resto))

    rx = Receptor()
    tramas = rx.alimentar(b''.join(flujo))
    limpio = {**rx.resumen(),
              'secuencia_consecutiva': [t['seq'] for t in tramas] == list(range(K)),
              'muestras_ok': sum(es_patron(t) for t in tramas)}
    limpio['cumple'] = (limpio['validas'] == K and limpio['muestras_ok'] == K and limpio['secuencia_consecutiva']
                        and limpio['errores_crc'] == 0 and limpio['bytes_descartados'] == 0)

    # Fallas: trama 4 con un bit alterado, trama 9 ausente, basura antes de la 12.
    con_fallas = [bytearray(f) for f in flujo]
    con_fallas[4][500] ^= 0x01
    del con_fallas[9]
    con_fallas.insert(11, bytearray(b'\x00\xa5\x00\xa5\x5a\x07\x13\xff\x5a\xa5'))
    rx = Receptor()
    tramas = rx.alimentar(b''.join(con_fallas))
    fallas = {**rx.resumen(),
              'muestras_ok': sum(es_patron(t) for t in tramas)}
    fallas['cumple'] = (fallas['validas'] == K - 2 and fallas['muestras_ok'] == K - 2
                        and fallas['errores_crc'] == 1 and fallas['perdidas'] == 2)
    return {'firmware_prueba_trama': firmware, 'python_tramas_conocidas': limpio, 'python_con_fallas': fallas,
            'bytes_por_trama': len(flujo[0])}


def prueba_parametros(con):
    """Diagnostica caso_1 y comprueba que la trama siguiente lleve los mismos parámetros que el DIAG."""
    parametros, _ = parametros_proyecto()
    con.configurar(parametros)
    x = np.load(RAIZ / 'pruebas/caso_1/muestras.npz')['contaminada'][:16000]
    diag = con.diagnosticar(x)[0]
    con.enviar(b'tramas_conocidas 1\n')
    t = Receptor().alimentar(bytes.fromhex(con.esperar('TRAMA')[1]))[0]
    con.esperar('OK')
    f32 = lambda v: np.float32(np.nan if v is None else v)  # la trama lleva float32
    iguales = lambda a, b: np.isnan(f32(a)) and np.isnan(f32(b)) or abs(f32(a) - f32(b)) <= 1e-3 * max(1, abs(f32(b)))
    r = {'diag_numero': t['diag_numero'] == diag['numero'],
         'tipos': t['tipos'] == diag['tipos'],
         'confianza': t['confianza_alta'] == (diag['confianza'] == 'alta'),
         'fin_banda_util_hz': iguales(t['fin_banda_util_hz'], diag['fin_banda_util_hz']),
         'lineas_hz': len(t['lineas_hz']) == min(4, len(diag['frecuencias_interferentes_hz'])) and all(
             iguales(a, b) for a, b in zip(t['lineas_hz'], diag['frecuencias_interferentes_hz'])),
         'banda_ruido_hz': all(iguales(a, b) for a, b in zip(t['banda_ruido_hz'], diag['banda_ruido_hz'] or [None, None])),
         'frecuencia_red_hz': iguales(t['frecuencia_red_hz'], diag['frecuencia_red_hz']),
         'snr_estimada_db': iguales(t['snr_estimada_db'], diag['snr_estimada_db']),
         'n_fft': t['n_fft'] == parametros['n_bloque'],
         'muestras_del_diagnostico': t['diag_muestras'] == diag['muestras'],
         'fin_del_diagnostico': t['diag_fin_muestra'] == diag['fin_muestra']}
    r = {k: bool(v) for k, v in r.items()}  # numpy.bool_ no se serializa a JSON
    return {**r, 'fin_banda_util_trama_hz': float(t['fin_banda_util_hz']), 'lineas_trama_hz': t['lineas_hz'],
            'cumple': all(r.values())}


def prueba_uart(puerto_uart, segundos, con=None):
    import serial
    if con:
        con.comando('fuente patron')
    uart = serial.Serial(puerto_uart, 921600, timeout=0.1)
    uart.reset_input_buffer()
    rx, marcas, bits_estado = Receptor(), [], {}
    muestras_ok = muestras_mal = 0
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        ahora = time.monotonic()
        for t in rx.alimentar(uart.read(4096)):
            marcas.append((t['seq'], ahora))
            for e in t['estado']:
                bits_estado[e] = bits_estado.get(e, 0) + 1
            if con:
                ok = es_patron(t)
                muestras_ok += ok
                muestras_mal += not ok
            ultima = t
    uart.close()
    if con:
        con.comando('fuente adc')
    if len(marcas) < 2:
        raise RuntimeError('No llegaron tramas: revise GPIO17 -> RX del adaptador, GND común y baudios.')
    # fs contra el reloj de la PC: muestras entre la primera y la última trama / tiempo transcurrido.
    (s0, t0), (s1, t1) = marcas[0], marcas[-1]
    fs_pc = (s1 - s0) * ultima['n_muestras'] / (t1 - t0)
    r = {**rx.resumen(), 'segundos': segundos, 'fs_reloj_pc_hz': fs_pc,
         'fs_medida_firmware_hz': ultima['fs_medida_hz'], 'error_fs_ppm': 1e6 * (fs_pc / 16000 - 1),
         'banderas_estado': bits_estado}
    if con:
        r.update(muestras_ok=muestras_ok, muestras_mal=muestras_mal)
    r['cumple'] = rx.errores_crc == 0 and rx.perdidas == 0 and abs(fs_pc / 16000 - 1) < 5e-3 and \
        (not con or muestras_mal == 0)
    return r


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--puerto', help='consola USB de la placa; sin él se usa host/nodo1_host')
    parser.add_argument('--uart', help='adaptador USB-UART conectado a GPIO17 (tramas reales)')
    parser.add_argument('--segundos', type=float, default=30)
    args = parser.parse_args()
    con = Conexion(args.puerto)
    resultado = {'origen': con.origen, **prueba_consola(con), 'parametros_en_trama': prueba_parametros(con)}
    if args.uart:
        resultado['uart'] = prueba_uart(args.uart, args.segundos, con if args.puerto else None)
    con.cerrar()

    claves = ('firmware_prueba_trama', 'python_tramas_conocidas', 'python_con_fallas', 'parametros_en_trama', 'uart')
    for clave in claves:
        if clave in resultado:
            r = resultado[clave]
            print(f"{clave:24s} {'CUMPLE' if r['cumple'] else 'NO CUMPLE'}  "
                  + ', '.join(f'{k}={v}' for k, v in r.items() if k != 'cumple'))
    salida = NODO1 / 'resultados' / f"validacion_tramas_{con.origen.split(':')[0]}.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps(resultado, indent=2), encoding='utf-8')
    print(f'Guardado en {salida}')
    todos = [resultado[k]['cumple'] for k in claves if k in resultado]
    raise SystemExit(0 if all(todos) else 1)


if __name__ == '__main__':
    main()
