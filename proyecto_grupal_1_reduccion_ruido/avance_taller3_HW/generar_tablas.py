"""Genera y verifica las muestras que usa el firmware. Requiere NumPy.
Ejecutar: python generar_tablas.py. No simula mediciones del hardware.
"""
from pathlib import Path
import json
import numpy as np

ROOT = Path(__file__).resolve().parent
FS, N = 16000, 4000  # 0.25 s: todos los tonos completan ciclos enteros.
t = np.arange(N) / FS
freqs = [440, 880, 1320, 2500, 2508, 3100]
tonos = {f: np.sin(2*np.pi*f*t) for f in freqs}
triple = sum(a*np.sin(2*np.pi*f*t + np.deg2rad(p))
             for f, a, p in zip([440,880,1320], [1,.55,.3], [0,35,-50]))
triple *= .8 / np.max(np.abs(triple))
ruido = tonos[2500] * np.sqrt(np.mean(triple**2) / (10**.2 * .5))
mezcla = triple + ruido
escala = .8 / np.max(np.abs(mezcla))
señales = [np.zeros(N), .8*tonos[440], .8*tonos[880], .8*tonos[1320],
           triple, .8*tonos[2500], .8*tonos[2508], .8*tonos[3100], mezcla*escala]
nombres = ['Reposo','440 Hz','880 Hz','1320 Hz','Tres tonos','2500 Hz','2508 Hz','3100 Hz','Tres tonos + ruido 2500 Hz, SNR 2 dB']
codigos = np.rint((np.array(señales)+1)*127.5).astype(np.uint8)
header = '#pragma once\n#include <stdint.h>\n// Generado por generar_tablas.py; copiar a RAM antes de activar la ISR.\n'
header += f'constexpr uint32_t FS_HZ = {FS};\nconstexpr uint32_t TABLE_N = {N};\nconstexpr uint32_t MODE_COUNT = {len(señales)};\n'
header += 'static const char* const MODE_NAMES[] = {' + ','.join(json.dumps(s) for s in nombres) + '};\n'
header += 'static const uint8_t TABLES[MODE_COUNT][TABLE_N] = {\n'
for row in codigos:
    header += '{\n' + '\n'.join(','.join(map(str,row[i:i+80]))+',' for i in range(0,N,80)) + '\n},\n'
header += '};\n'
(ROOT/'emisor_esp32s3'/'tablas.h').write_text(header)
# Verificar los bytes que se entregan, no solamente la señal ideal.
import re
body = header.split('TABLES[MODE_COUNT][TABLE_N] = {')[1]
parsed = np.array([int(v) for v in re.findall(r'\d+', body)], dtype=np.uint8).reshape(codigos.shape)
assert np.array_equal(parsed,codigos)
assert int(parsed.min()) >= 25 and int(parsed.max()) <= 230
rows=[]
for mode,f in [(1,440),(2,880),(3,1320),(5,2500),(6,2508),(7,3100)]:
    x=parsed[mode].astype(float); x-=x.mean()
    spectrum=np.abs(np.fft.rfft(x))
    measured=np.argmax(spectrum[1:])+1
    measured *= FS/N
    assert measured == f
    rows.append({'modo':mode, 'frecuencia_fft_hz':measured})
for f in [440,880,1320]:
    sp=np.abs(np.fft.rfft(parsed[4].astype(float)-parsed[4].mean()))
    k=round(f*N/FS)
    assert sp[k] > 20*np.median(sp[1:])
snr=10*np.log10(np.mean((triple*escala)**2)/np.mean((ruido*escala)**2))
assert abs(snr-2)<1e-10
report={'tipo':'Verificacion digital; NO medicion fisica ni compilacion', 'fs_hz':FS,
        'longitud_tabla':N,'ram_tablas_bytes':int(parsed.nbytes),'rango_codigos':[int(parsed.min()),int(parsed.max())],
        'tonos_verificados':rows,'snr_mezcla_antes_cuantizacion_db':float(snr),
        'nota':'N FFT receptor sigue siendo 1024; TABLE_N es solo el periodo de sintesis.'}
(ROOT/'validacion_digital.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
