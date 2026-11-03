"""Verifica en la computadora las señales que calcula el firmware del emisor.

Compila prueba_generador.cpp (que usa el mismo generador.h del firmware) con g++,
lo ejecuta para cada prueba P1–P5 y compara contra lo configurado y contra pruebas/.
Ejecutar desde la carpeta del proyecto: python emisor/prueba/verificar_generador.py
No reemplaza la medición en la placa: no incluye el DAC, el temporizador ni el canal.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfreqz, welch

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
FS = 16000
BANDAS = {2: (2500, 3800), 3: (2000, 7500), 5: (1000, 1800)}
resultados = []


def revisar(nombre, condicion, detalle=''):
    resultados.append((nombre, bool(condicion), detalle))


def snr(s, r):
    return 10 * np.log10(np.sum(s ** 2) / np.sum(r ** 2))


def pico_hz(x):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.argmax(X) * FS / len(x)


def main():
    if not shutil.which('g++'):
        sys.exit('Se necesita g++ para compilar prueba_generador.cpp.')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        exe = tmp / 'prueba_generador'
        subprocess.run(['g++', '-O2', '-std=c++17', '-Wall', '-o', str(exe), str(AQUI / 'prueba_generador.cpp')], check=True)

        def correr(segundos, **params):
            salida = tmp / 'x.f32'
            args = [str(exe), str(salida), str(int(segundos * FS))] + [f'{k}={v}' for k, v in params.items()]
            subprocess.run(args, check=True, capture_output=True)
            return np.fromfile(salida, dtype=np.float32).astype(np.float64)

        # 1. Cada prueba: SNR de 2 dB, mezcla = limpia + ruido y sin saturar el DAC.
        for p in range(1, 6):
            l, r, m = (correr(30, prueba=p, comp=c) for c in ('limpia', 'ruido', 'mezcla'))
            # El impulsivo tiene pocos eventos (≈ 120 en 30 s): su potencia fluctúa más.
            tol = 1.0 if p == 4 else 0.3
            revisar(f'P{p}: SNR 2 dB', abs(snr(l, r) - 2) < tol, f'{snr(l, r):.2f} dB')
            revisar(f'P{p}: mezcla = limpia + ruido', np.allclose(m, l + r, atol=1e-6), 'misma ganancia en las tres componentes')
            revisar(f'P{p}: sin saturar', np.max(np.abs(m)) <= 1, f'pico {np.max(np.abs(m)):.3f}')

        # 2. Contenido de cada prueba.
        l, r = (correr(2, prueba=1, comp=c) for c in ('limpia', 'ruido'))
        revisar('P1: tono útil en 440 Hz', abs(pico_hz(l) - 440) <= FS / len(l), f'{pico_hz(l):.2f} Hz')
        revisar('P1: interferencia en 2508 Hz', abs(pico_hz(r) - 2508) <= FS / len(r), f'{pico_hz(r):.2f} Hz')
        for p, (f1, f2) in BANDAS.items():
            # Mismo espectro que butter(6, ...) con sosfiltfilt en src/generacion.py.
            r = correr(20, prueba=p, comp='ruido')
            f, psd = welch(r, FS, nperseg=1024)
            _, H = sosfreqz(butter(6, [f1, f2], 'bandpass', fs=FS, output='sos'), worN=f, fs=FS)
            esperado = np.abs(H) ** 4
            esperado *= psd.sum() / esperado.sum()
            zona = esperado > esperado.max() * 1e-2
            desvio = np.max(np.abs(10 * np.log10(psd[zona] / esperado[zona])))
            revisar(f'P{p}: ruido de banda {f1}–{f2} Hz igual a generacion.py', desvio < 1.5,
                    f'desvío máximo de la PSD {desvio:.2f} dB (hasta −20 dB del máximo)')
        with np.load(RAIZ / 'pruebas/caso_5/muestras.npz') as d:
            ref = d['limpia']
        a = correr(len(ref) / FS, prueba=3, comp='limpia')
        a *= np.dot(a, ref) / np.dot(a, a)
        revisar('P3: audio igual a la limpia de caso_5', snr(ref, ref - a) > 30, f'error {snr(ref, ref - a):.1f} dB bajo la señal (int8)')
        # P4: caso_6 tiene ráfagas en t = 1…5 s; el emisor las repite desde t = 0.
        with np.load(RAIZ / 'pruebas/caso_6/muestras.npz') as d:
            ref = d['limpia'][FS:5 * FS + 800]
        a = correr(6, prueba=4, comp='limpia')[FS:5 * FS + 800]
        a *= np.dot(a, ref) / np.dot(a, a)
        revisar('P4: chirp igual a la limpia de caso_6', snr(ref, ref - a) > 60, f'error {snr(ref, ref - a):.1f} dB bajo la señal')
        r = correr(30, prueba=4, comp='ruido')
        eventos = int(np.count_nonzero(r))
        revisar('P4: ruido impulsivo a 4/s', 80 <= eventos <= 160, f'{eventos} impulsos en 30 s')

        # 3. Parámetros que se cambian por serial durante la defensa.
        l, r = (correr(10, prueba=2, snr=10, comp=c) for c in ('limpia', 'ruido'))
        revisar('snr 10 sobre P2', abs(snr(l, r) - 10) < 0.3, f'{snr(l, r):.2f} dB')
        t = correr(2, tonos='1000:1', ruido='ninguno', comp='limpia')
        revisar('tonos configurables', abs(pico_hz(t) - 1000) <= FS / len(t), f'{pico_hz(t):.2f} Hz')
        r = correr(2, prueba=1, ruido='tono:3300', comp='ruido')
        revisar('frecuencia del ruido configurable', abs(pico_hz(r) - 3300) <= FS / len(r), f'{pico_hz(r):.2f} Hz')
        x = correr(2, prueba=2)
        revisar('vol 0.5 reduce el pico a la mitad', np.allclose(correr(2, prueba=2, vol=0.5), x / 2, atol=1e-6))
        revisar('misma semilla, misma señal', np.array_equal(x, correr(2, prueba=2)))
        revisar('otra semilla, otra señal', not np.array_equal(x, correr(2, prueba=2, semilla=99)))

    ancho = max(len(r[0]) for r in resultados)
    for nombre, ok, detalle in resultados:
        print(f"{'OK   ' if ok else 'FALLA'} {nombre:<{ancho}}  {detalle}")
    fallas = sum(not ok for _, ok, _ in resultados)
    print(f'\n{len(resultados) - fallas}/{len(resultados)} verificaciones correctas')
    sys.exit(1 if fallas else 0)


if __name__ == '__main__':
    main()
