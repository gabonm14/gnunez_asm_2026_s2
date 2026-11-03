"""Exporta la canción de P3 a emisor/audio.h para guardarla en la flash del emisor.

Ejecutar desde la carpeta del proyecto: python emisor/generar_audio.py
Es la única señal que viene de la computadora: el resto lo genera el ESP32 en vivo.
Usa la misma lectura, remuestreo y fade que el caso_5 de src/generacion.py.
"""
import json
from pathlib import Path
import sys

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.generacion import cargar_audio

SALIDA = Path(__file__).resolve().parent / 'audio.h'


def generar():
    config = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))
    caso = next(c for c in config['casos'] if c.get('senal', {}).get('tipo') == 'audio')
    fs = config['fs_hz']
    n = int(fs * config['duracion_s'])
    x = cargar_audio(RAIZ / caso['senal']['archivo'], fs, n)
    # Fade al inicio y al final: evita un clic cada vez que el audio vuelve a empezar.
    n_fade = int(fs * config['fade_ms'] / 1000)
    rampa = np.sin(np.linspace(0, np.pi / 2, n_fade)) ** 2
    x[:n_fade] *= rampa
    x[-n_fade:] *= rampa[::-1]
    codigos = np.rint(x / np.max(np.abs(x)) * 127).astype(np.int8)
    potencia = float(np.mean((codigos / 127.0) ** 2))
    filas = (','.join(map(str, codigos[i:i + 64])) for i in range(0, n, 64))
    texto = ('#pragma once\n#include <stdint.h>\n'
             f'// Generado por generar_audio.py desde {caso["senal"]["archivo"]}. No editar a mano.\n'
             f'constexpr uint32_t FS_HZ = {fs};\n'
             f'constexpr uint32_t AUDIO_N = {n};\n'
             f'constexpr float AUDIO_POTENCIA = {potencia:.9g}f;  // media de x² con x = código / 127\n'
             f'static const int8_t AUDIO[AUDIO_N] = {{\n' + ',\n'.join(filas) + '\n};\n')
    SALIDA.write_text(texto, encoding='utf-8')
    print(f'{SALIDA.name}: {caso["senal"]["archivo"]}, {n} muestras ({n / fs:.1f} s), {n} bytes')


if __name__ == '__main__':
    generar()
