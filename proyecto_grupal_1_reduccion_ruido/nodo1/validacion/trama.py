"""Formato de la trama del nodo 1 y decodificador independiente del firmware.

Todo en little-endian. El CRC-32 es zlib.crc32 sobre todo menos el delimitador y el CRC.

    off  tam  campo
      0    2  delimitador A5 5A
      2    1  versión (3)
      3    1  longitud de cabecera (92)
      4    4  secuencia del bloque
      8    2  n_muestras (1024)
     10    2  estado (bits en ESTADOS)
     12    2  muestras recortadas en el bloque
     14    2  muestras atrasadas en el bloque
     16    4  bloques perdidos acumulados
     20    4  fs medida (float32, Hz)
     24    4  número del último diagnóstico (0: aún no hay)
     28    1  tipos de ruido (bits: impulsivo, red, tonal, banda)
     29    1  banderas (bits: confianza alta, solapamiento, banda ancha, impulsivo)
     30    1  líneas válidas (<= 4)
     31    1  reservado
     32    4  fin de banda útil (Hz, NaN si la confianza es baja)
     36   16  frecuencias interferentes [4] (Hz)
     52    8  banda de ruido [lo, hi] (Hz)
     60    4  frecuencia de red (Hz)
     64    4  SNR estimada (dB)
     68    2  N de la FFT del diagnóstico
     70    2  DC restada (código del ADC)
     72    4  marca de tiempo: esp_timer al cerrar el bloque (µs, módulo 2^32)
     76    4  índice absoluto (seq*1024 + i) donde cerró el último diagnóstico
     80    4  muestras que cubrió ese diagnóstico
     84    4  posición en el ciclo del emisor de la primera muestra (0xFFFFFFFF: sin pulso)
     88    2  índice en el bloque donde empieza un ciclo (int16, −1 si ninguno)
     90    1  componente que emite el emisor, por el ancho del pulso (COMPONENTES)
     91    1  estado de la referencia (ESTADOS_REF)
     92  2*n  muestras int16 con la DC quitada (unidades de código del ADC)
    ...  2*n  solo con el bit "referencia" del estado: referencia limpia de esas muestras
              (int16, mismas unidades; −32768 = sin referencia para esa muestra)
    ...    4  CRC-32
"""
import struct
import zlib

import numpy as np

SYNC = b'\xa5\x5a'
VERSION = 3
CABECERA = 92
FORMATO = struct.Struct('<2sBBIHHHHIfIBBBxf4f2fffHHIIIIhBB')
ESTADOS = ('recorte', 'atraso', 'perdida', 'diag_nuevo', 'fs_fuera', 'prueba', 'referencia')
COMPONENTES = ('ninguna', 'mezcla', 'limpia', 'ruido')
ESTADOS_REF = ('vacia', 'esperando', 'capturando', 'lista')
REF_SIN = -32768
SIN_POSICION = 0xFFFFFFFF
TIPOS = ('impulsivo', 'red_electrica', 'tonal', 'banda')
assert FORMATO.size == CABECERA


def patron(seq, n):
    """Bloque conocido de las pruebas; igual a patron() del firmware.
    Las tramas impares llevan además la referencia −patron."""
    return (((seq * 7 + np.arange(n) * 13) & 0xFFF) - 2048).astype(np.int16)


def es_patron(t):
    """La trama trae el patrón conocido y, si es impar, la referencia conocida."""
    ok = np.array_equal(t['muestras'], patron(t['seq'], t['n_muestras']))
    if t['seq'] % 2:
        return ok and t['referencia'] is not None and np.array_equal(t['referencia'], -patron(t['seq'], t['n_muestras']))
    return ok and t['referencia'] is None


def interpretar(trama):
    """Diccionario con los campos de una trama ya validada."""
    c = FORMATO.unpack_from(trama)
    n = c[4]
    bits = lambda valor, nombres: [x for i, x in enumerate(nombres) if valor >> i & 1]
    return {'seq': c[3], 'n_muestras': n, 'estado': bits(c[5], ESTADOS), 'recortadas': c[6],
            'atrasadas': c[7], 'perdidos_acumulados': c[8], 'fs_medida_hz': c[9], 'diag_numero': c[10],
            'tipos': bits(c[11], TIPOS), 'confianza_alta': bool(c[12] & 1), 'n_lineas': c[13],
            'fin_banda_util_hz': c[14], 'lineas_hz': list(c[15:15 + c[13]]), 'banda_ruido_hz': list(c[19:21]),
            'frecuencia_red_hz': c[21], 'snr_estimada_db': c[22], 'n_fft': c[23], 'dc_codigo': c[24],
            't_us': c[25], 'diag_fin_muestra': c[26], 'diag_muestras': c[27],
            'posicion_ciclo': None if c[28] == SIN_POSICION else c[28], 'inicio_ciclo': c[29],
            'componente': COMPONENTES[c[30] & 3], 'ref_estado': ESTADOS_REF[c[31] & 3],
            'muestras': np.frombuffer(trama, '<i2', n, CABECERA),
            'referencia': np.frombuffer(trama, '<i2', n, CABECERA + 2 * n) if c[5] >> 6 & 1 else None}


class Receptor:
    """Busca el delimitador, valida cabecera y CRC, y cuenta pérdidas por la secuencia."""

    def __init__(self):
        self.pendiente = bytearray()
        self.ok = self.errores_crc = self.perdidas = self.descartados = 0
        self.ultima_seq = None

    def alimentar(self, datos):
        """Agrega bytes y devuelve las tramas válidas completas (como diccionarios)."""
        self.pendiente += datos
        tramas = []
        while True:
            i = self.pendiente.find(SYNC)
            if i < 0:
                corte = len(self.pendiente) - (self.pendiente[-1:] == SYNC[:1])  # un A5 final puede iniciar
                self.descartados += corte
                del self.pendiente[:corte]
                return tramas
            self.descartados += i
            del self.pendiente[:i]
            if len(self.pendiente) < 12:
                return tramas
            n = int.from_bytes(self.pendiente[8:10], 'little')
            if self.pendiente[2] != VERSION or self.pendiente[3] != CABECERA or not 0 < n <= 2048:
                self.descartados += 1
                del self.pendiente[:1]
                continue
            con_ref = int.from_bytes(self.pendiente[10:12], 'little') >> 6 & 1
            largo = CABECERA + 2 * n * (2 if con_ref else 1) + 4
            if len(self.pendiente) < largo:
                return tramas
            trama = bytes(self.pendiente[:largo])
            if zlib.crc32(trama[2:-4]) != int.from_bytes(trama[-4:], 'little'):
                self.errores_crc += 1
                self.descartados += 1
                del self.pendiente[:1]  # se busca otro delimitador dentro de la trama mala
                continue
            del self.pendiente[:largo]
            t = interpretar(trama)
            if self.ultima_seq is not None and t['seq'] != self.ultima_seq + 1:
                self.perdidas += (t['seq'] - self.ultima_seq - 1) % 2 ** 32
            self.ultima_seq = t['seq']
            self.ok += 1
            tramas.append(t)

    def resumen(self):
        return {'validas': self.ok, 'errores_crc': self.errores_crc, 'perdidas': self.perdidas,
                'bytes_descartados': self.descartados}
