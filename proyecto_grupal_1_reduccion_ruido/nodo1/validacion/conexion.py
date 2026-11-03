"""Conexión con el nodo 1: la placa por puerto serie o el ejecutable de PC (host/nodo1_host).

Ambos hablan el mismo protocolo de nodo1_consola.cpp, así los scripts de validación
sirven igual con y sin hardware.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

NODO1 = Path(__file__).resolve().parents[1]
RAIZ = NODO1.parent
HOST = NODO1 / 'host' / 'nodo1_host'
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


class Conexion:
    def __init__(self, puerto=None, baudios=921600, timeout=30):
        self.timeout = timeout
        if puerto:
            import serial  # pyserial, solo hace falta con la placa
            self.serie = serial.Serial(puerto, baudios, timeout=timeout)
            time.sleep(2)  # abrir el puerto puede reiniciar la placa
            self.serie.reset_input_buffer()
            self.proceso = None
            self.origen = f'esp32:{puerto}'
            # Sin fuente activa: los DIAG periódicos del ADC se mezclarían con los de la prueba.
            self.comando('fuente nada')
        else:
            subprocess.run(['make', '-s', '-C', str(HOST.parent)], check=True)  # recompila si cambió el .ino
            self.proceso = subprocess.Popen([str(HOST)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            self.serie = None
            self.origen = 'host'

    def enviar(self, datos):
        if self.serie:
            self.serie.write(datos)
            self.serie.flush()
        else:
            self.proceso.stdin.write(datos)
            self.proceso.stdin.flush()

    def linea(self):
        texto = (self.serie.readline() if self.serie else self.proceso.stdout.readline()).decode('utf-8').strip()
        if not texto and self.serie:
            raise TimeoutError('El nodo 1 no respondió.')
        return texto

    def esperar(self, *etiquetas):
        """Lee hasta una línea con alguna etiqueta; un ERR detiene el script."""
        while True:
            texto = self.linea()
            etiqueta, _, resto = texto.partition(' ')
            if etiqueta == 'ERR':
                raise RuntimeError(texto)
            if etiqueta in etiquetas:
                return etiqueta, resto

    def comando(self, texto, *etiquetas):
        self.enviar((texto + '\n').encode())
        return self.esperar(*(etiquetas or ('OK',)))

    def configurar(self, parametros):
        for clave, valor in parametros.items():
            self.comando(f'set {clave} {valor}')
        return json.loads(self.comando('cfg', 'CFG')[1])

    def diagnosticar(self, x, periodico=False):
        """Envía x como float32 y devuelve la lista de diagnósticos (uno, o uno por periodo)."""
        x = np.ascontiguousarray(x, dtype='<f4')
        self.comando(f'muestras {len(x)}' + (' periodico' if periodico else ''))
        datos = x.tobytes()
        for i in range(0, len(datos), 4096):
            self.enviar(datos[i:i + 4096])
        diags = []
        while True:
            etiqueta, resto = self.esperar('DIAG', 'FIN')
            if etiqueta == 'FIN':
                return diags
            diags.append(json.loads(resto))

    def cerrar(self):
        if self.serie:
            self.comando('fuente adc')  # deja la placa capturando otra vez
            self.serie.close()
        else:
            self.proceso.stdin.close()
            self.proceso.wait()


def parametros_proyecto():
    """Parámetros del nodo 1 tomados de metadatos/, para que placa y Python usen los mismos."""
    leer = lambda nombre: json.loads((RAIZ / 'metadatos' / nombre).read_text(encoding='utf-8-sig'))
    diag, esp, pipe = leer('diagnostico.json'), leer('filtro_espectral.json'), leer('pipeline.json')
    claves = ('umbral_ocupacion_db', 'hueco_fusion_bins', 'ancho_linea_hz', 'ancho_dc_hz', 'hueco_util_hz',
              'margen_banda_util_hz', 'umbral_curtosis', 'k_atipicas_mad', 'armonicos_red_min',
              'max_armonico_red', 'tolerancia_red_hz')
    p = {'fs_hz': esp['fs_hz'], 'n_bloque': esp['n_bloque'],
         'periodo_diag_ms': 1000 * pipe['segundos_diagnostico'], **{k: diag[k] for k in claves}}
    p['frecuencia_red_a_hz'], p['frecuencia_red_b_hz'] = diag['frecuencias_red_hz']
    return p, diag
