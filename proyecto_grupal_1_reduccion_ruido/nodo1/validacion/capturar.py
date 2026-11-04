"""Captura las tramas reales del nodo 1 en un archivo .npz para analizarlas después.

Sin adaptador (--usb): el nodo copia cada trama por el mismo cable USB de la consola
("tramas_usb on"); GPIO17 sigue enviando a los nodos 2 y 3.

    python nodo1/validacion/capturar.py --usb COM3 --segundos 12 \\
        --salida nodo1/capturas/p1_limpia.npz --nota "P1 comp limpia, 30 cm, MAX4466 a 25x"

Con --ref K, antes de capturar guarda en el nodo la referencia limpia para el MSE: pide poner
el emisor en comp limpia, espera a que el nodo la guarde y pide pasar a comp mezcla.

Con adaptador (--uart): se lee la UART2 (GPIO17 -> RX del adaptador, GND común).
Con --puerto (consola USB) además se cargan los parámetros de metadatos/, se pone la fuente
y al final se guarda el estado del comando "adc".

    python nodo1/validacion/capturar.py --uart COM4 --puerto COM3 --segundos 12 \\
        --salida nodo1/capturas/caso_1_r1.npz --nota "caso_1, 50 cm, pot. micrófono a 1/2"

Sin hardware, --simular CASO pasa la mezcla de pruebas/CASO por el firmware (placa con
--puerto o el ejecutable de PC) con "muestras ... periodico tramas": mismo DC, diagnóstico y
tramas que la captura real, sin canal acústico. Sirve para probar analizar_captura.py.

    python nodo1/validacion/capturar.py --simular caso_1 --salida nodo1/capturas/sim_caso_1.npz

Luego: python nodo1/validacion/analizar_captura.py nodo1/capturas/caso_1_r*.npz --caso caso_1
"""
import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np

from conexion import RAIZ, Conexion, parametros_proyecto
from trama import COMPONENTES, ESTADOS, ESTADOS_REF, REF_SIN, Receptor

CAMPOS_DIAG = ('diag_numero', 'diag_fin_muestra', 'diag_muestras', 'tipos', 'confianza_alta', 'fin_banda_util_hz',
               'lineas_hz', 'banda_ruido_hz', 'frecuencia_red_hz', 'snr_estimada_db', 'n_fft')


def capturar(puerto_uart, segundos, con=None, fuente='adc'):
    import serial
    if con:
        con.configurar(parametros_proyecto()[0])
        con.comando(f'fuente {fuente}')
        con.comando('adc', 'ADC')  # reinicia la ventana de mín./máx.
    uart = serial.Serial(puerto_uart, 921600, timeout=0.1)
    uart.reset_input_buffer()
    rx, tramas = Receptor(), []
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        ahora = time.monotonic()
        tramas += [(t, ahora) for t in rx.alimentar(uart.read(4096))]
    uart.close()
    estado_adc = json.loads(con.comando('adc', 'ADC')[1]) if con else None
    if not tramas:
        raise RuntimeError('No llegaron tramas: revise GPIO17 -> RX del adaptador, GND común y baudios.')
    return tramas, rx.resumen(), estado_adc


def guardar_referencia(con, ciclos, periodo_max_s=7):
    """Guarda la referencia limpia en el nodo ("ref capturar") y espera a que quede lista."""
    input('Ponga el emisor en "comp limpia" y presione Enter... ')
    con.comando(f'ref capturar {ciclos}')
    espera = con.serie.timeout
    con.serie.timeout = ciclos * periodo_max_s + 10  # P3: ciclos de 6 s
    print(f'Guardando {ciclos} ciclos de la limpia...')
    resto = con.esperar('REF')[1]  # un "ERR ref cancelada" detiene el script
    con.serie.timeout = espera
    r = json.loads(resto)
    print(f"Referencia lista: {r['muestras']} muestras, periodo {r['periodo_ref']}, RMS {r['rms_codigos']} códigos")
    input('Ponga el emisor en la componente que quiere capturar (normalmente "comp mezcla") y presione Enter... ')


def capturar_usb(con, segundos, fuente='adc', ref=0):
    """Tramas copiadas por la consola USB (tramas_usb on); el texto intercalado se descarta."""
    con.configurar(parametros_proyecto()[0])
    con.comando(f'fuente {fuente}')
    if ref:
        guardar_referencia(con, ref)
    con.comando('adc', 'ADC')  # reinicia la ventana de mín./máx.
    con.comando('tramas_usb on')
    serie, espera = con.serie, con.serie.timeout
    serie.timeout = 0.1
    rx, tramas = Receptor(), []
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        ahora = time.monotonic()
        tramas += [(t, ahora) for t in rx.alimentar(serie.read(4096))]
    con.enviar(b'tramas_usb off\n')
    time.sleep(0.5)  # que terminen de llegar las tramas en camino antes de volver a leer texto
    serie.reset_input_buffer()
    serie.timeout = espera
    estado_adc = json.loads(con.comando('adc', 'ADC')[1])
    if not tramas:
        raise RuntimeError('No llegaron tramas por USB: revise que el firmware tenga tramas_usb.')
    return tramas, rx.resumen(), estado_adc


def simular(con, caso, segundos, componente='contaminada', pico_codigos=1500):
    """Envía una componente del caso como si viniera del ADC y junta las tramas.

    Todas las componentes usan la escala de la mezcla (±pico_codigos), como en el emisor:
    así las capturas simuladas de limpia, ruido y mezcla se pueden comparar entre sí.
    """
    con.configurar(parametros_proyecto()[0])
    d = np.load(RAIZ / 'pruebas' / caso / 'muestras.npz')
    escala = pico_codigos / np.abs(d['contaminada']).max() / 2048  # el nodo multiplica por 2048
    x = (d[componente][:int(16000 * segundos)] * escala).astype('<f4')
    con.comando(f'muestras {len(x)} periodico tramas')
    # Se envía en otro hilo: el nodo responde tramas mientras recibe, y si nadie las lee se
    # llena la tubería de salida y ambos lados quedan esperando.
    envio = threading.Thread(target=lambda: [con.enviar(x[i:i + 1024].tobytes()) for i in range(0, len(x), 1024)])
    envio.start()
    rx, tramas = Receptor(), []
    while True:
        etiqueta, resto = con.esperar('TRAMA', 'FIN')
        if etiqueta == 'FIN':
            envio.join()
            return tramas, rx.resumen(), None
        tramas += [(t, t['seq'] * 0.064) for t in rx.alimentar(bytes.fromhex(resto))]


def a_arreglos(tramas):
    """Muestras ordenadas por secuencia; los bloques perdidos quedan en 0 con valido=False."""
    n = tramas[0][0]['n_muestras']
    seq = np.array([t['seq'] for t, _ in tramas], dtype=np.int64)
    seq0 = int(seq[0])
    muestras = np.zeros((int(seq[-1]) - seq0 + 1) * n, dtype=np.int16)
    valido = np.zeros(len(muestras), dtype=bool)
    for t, _ in tramas:
        i = (t['seq'] - seq0) * n
        muestras[i:i + n] = t['muestras']
        valido[i:i + n] = True
    bits = lambda t: sum(1 << ESTADOS.index(e) for e in t['estado'])
    referencia = np.full(len(muestras), REF_SIN, dtype=np.int16)  # alineada muestra a muestra con muestras
    for t, _ in tramas:
        if t['referencia'] is not None:
            i = (t['seq'] - seq0) * n
            referencia[i:i + n] = t['referencia']
    diags = {}
    for t, _ in tramas:  # un registro por diagnóstico distinto, tal como viajó en la trama
        if t['diag_numero'] and t['diag_numero'] not in diags:
            diags[t['diag_numero']] = {k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in t.items()
                                       if k in CAMPOS_DIAG}
    return {'muestras': muestras, 'valido': valido, 'seq': seq, 'seq0': seq0, 'n_bloque': n,
            'estado': np.array([bits(t) for t, _ in tramas], dtype=np.uint16),
            'recortadas': np.array([t['recortadas'] for t, _ in tramas]),
            'atrasadas': np.array([t['atrasadas'] for t, _ in tramas]),
            'perdidos_acumulados': np.array([t['perdidos_acumulados'] for t, _ in tramas]),
            'fs_medida_hz': np.array([t['fs_medida_hz'] for t, _ in tramas]),
            'dc_codigo': np.array([t['dc_codigo'] for t, _ in tramas]),
            't_us': np.array([t['t_us'] for t, _ in tramas], dtype=np.uint32),
            't_pc': np.array([ahora for _, ahora in tramas]),
            'referencia': referencia,
            'posicion_ciclo': np.array([-1 if t['posicion_ciclo'] is None else t['posicion_ciclo'] for t, _ in tramas]),
            'componente': np.array([COMPONENTES.index(t['componente']) for t, _ in tramas], dtype=np.uint8),
            'ref_estado': np.array([ESTADOS_REF.index(t['ref_estado']) for t, _ in tramas], dtype=np.uint8),
            'diags': json.dumps(list(diags.values()), allow_nan=True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--usb', help='consola USB de la placa: las tramas vienen por el mismo cable')
    parser.add_argument('--uart', help='adaptador USB-UART conectado a GPIO17')
    parser.add_argument('--simular', metavar='CASO', help='sin micrófono: pasar pruebas/CASO por el firmware')
    parser.add_argument('--ref', type=int, default=0, metavar='K',
                        help='con --usb: antes de capturar guarda la referencia limpia (K ciclos, 1..8)')
    parser.add_argument('--componente', default='contaminada', choices=('contaminada', 'limpia', 'ruido'),
                        help='con --simular: qué componente del caso se envía')
    parser.add_argument('--puerto', help='consola USB de la placa (opcional)')
    parser.add_argument('--segundos', type=float, default=12, help='criterio: al menos 10 s por prueba')
    parser.add_argument('--fuente', default='adc', choices=('adc', 'sint'))
    parser.add_argument('--salida', required=True, type=Path)
    parser.add_argument('--nota', default='', help='condiciones: caso, distancia, ganancia, volumen')
    args = parser.parse_args()
    if sum(map(bool, (args.usb, args.uart, args.simular))) != 1:
        parser.error('use --usb PUERTO, --uart PUERTO (captura real) o --simular CASO')
    con = Conexion(args.usb or args.puerto) if args.usb or args.puerto or args.simular else None
    if args.simular:
        tramas, resumen, estado_adc = simular(con, args.simular, args.segundos, args.componente)
    elif args.usb:
        tramas, resumen, estado_adc = capturar_usb(con, args.segundos, args.fuente, args.ref)
    else:
        tramas, resumen, estado_adc = capturar(args.uart, args.segundos, con, args.fuente)
    if con:
        con.cerrar()
    datos = a_arreglos(tramas)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.salida, **datos, receptor=json.dumps(resumen), estado_adc=json.dumps(estado_adc),
                        nota=args.nota, segundos=args.segundos)
    con_ref = int(np.sum(datos['referencia'] != REF_SIN))
    print(f"{resumen['validas']} tramas, {resumen['perdidas']} perdidas, {resumen['errores_crc']} con CRC malo, "
          f"{len(json.loads(datos['diags']))} diagnósticos, {con_ref} muestras con referencia. Guardado en {args.salida}")


if __name__ == '__main__':
    main()
