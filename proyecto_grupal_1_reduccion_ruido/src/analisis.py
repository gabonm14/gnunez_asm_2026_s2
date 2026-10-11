"""Caracterización y experimentos de Fourier para la Tarea 1.

Convención: FFT sin normalizar, IFFT con factor 1/N (NumPy).
Los espectros gráficos usan bloques de N muestras con Hann periódica.
La energía se calcula SIN ventana sobre toda la señal mediante Parseval.
Fuentes teóricas: apuntes S6L2, S7L1 y S7L2 de CE1110.
"""
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import get_window

# Permite ejecutar desde VS Code o importar desde el notebook.
if __package__ in (None, ""):
    from generacion import RAIZ, generar_todos
else:
    from .generacion import RAIZ, generar_todos


def guardar_csv(ruta, filas):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open('w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def dft_directa(x):
    """X[k] = sum_n x[n] exp(-j 2 pi k n/N); referencia O(N**2).

    Se usa con N pequeño: la matriz compleja ocupa O(N**2) memoria.
    No es el algoritmo que trasladaremos al microcontrolador.
    """
    x = np.asarray(x)
    if x.ndim != 1 or len(x) == 0:
        raise ValueError('Se requiere un vector no vacío.')
    n = np.arange(len(x))
    return np.exp(-2j * np.pi * np.outer(n, n) / len(x)) @ x


def espectro_bloque(x, fs, ventana='hann', umbral_fase_db=-60):
    """Espectro unilateral con amplitud corregida por ganancia coherente.

    A[k] = 2|X[k]|/sum(w), salvo DC y Nyquist. La corrección es exacta
    para tonos aislados centrados en bins, no para tonos entre bins.
    Se oculta la fase por debajo de un umbral relativo al máximo.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or len(x) < 2 or fs <= 0:
        raise ValueError('Se requiere una señal real y fs positiva.')
    if ventana not in ('hann', 'boxcar'):
        raise ValueError('Use hann o boxcar (rectangular).')
    w = get_window(ventana, len(x), fftbins=True)
    X = np.fft.rfft(x * w)
    amplitud = 2 * np.abs(X) / np.sum(w)
    amplitud[0] /= 2
    if len(x) % 2 == 0:
        amplitud[-1] /= 2
    fase = np.angle(X)
    limite = np.max(amplitud) * 10 ** (umbral_fase_db / 20)
    fase[(amplitud < limite) | (amplitud == 0)] = np.nan
    return {'frecuencia_hz': np.fft.rfftfreq(len(x), 1 / fs),
            'amplitud': amplitud,
            'magnitud_db': 20 * np.log10(np.maximum(amplitud, 1e-12)),
            'fase_rad': fase, 'X': X}


def energia_por_bandas(x, fs, limites):
    """E = sum |x[n]|**2 = sum |X[k]|**2/N.

    Las bandas particionan [0, fs/2]. Interior: [inferior, superior).
    La última incluye Nyquist. No es una PSD ni una medida de SNR.
    """
    x = np.asarray(x, dtype=np.float64)
    limites = np.asarray(limites, dtype=float)
    if x.ndim != 1 or not len(x) or fs <= 0:
        raise ValueError('Se requiere un vector real no vacío y fs positiva.')
    if (len(limites) < 2 or limites[0] != 0 or
            not np.isclose(limites[-1], fs / 2) or np.any(np.diff(limites) <= 0)):
        raise ValueError('Los límites deben particionar desde 0 hasta Nyquist.')
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / fs)
    energia_bin = np.abs(X) ** 2 / len(x)
    energia_bin[1:] *= 2
    if len(x) % 2 == 0:
        energia_bin[-1] /= 2
    total = float(np.sum(x * x))
    filas = []
    for i, (inferior, superior) in enumerate(zip(limites[:-1], limites[1:])):
        mascara = (f >= inferior) & ((f <= superior) if i == len(limites) - 2 else (f < superior))
        energia = float(np.sum(energia_bin[mascara]))
        filas.append({'inferior_hz': float(inferior), 'superior_hz': float(superior),
                      'energia': energia,
                      'porcentaje': 100 * energia / total if total > 0 else 0.0})
    return filas


def error_simetria(x):
    """Error máximo de X[k] = conj(X[(-k) mod N]) para entrada real."""
    X = np.fft.fft(x)
    espejo = (-np.arange(len(X))) % len(X)
    return float(np.max(np.abs(X - np.conj(X[espejo]))))


def guardar_figura(fig, ruta):
    fig.tight_layout()
    fig.savefig(ruta, dpi=160, bbox_inches='tight')
    plt.close(fig)


def analizar_todos(casos, salida=None):
    """Guarda una figura de caracterización por caso y tablas auditables."""
    salida = Path(salida) if salida else RAIZ / 'resultados'
    figuras = salida / 'figuras'
    figuras.mkdir(parents=True, exist_ok=True)
    tabla_energia, tabla_resumen = [], []
    for nombre, datos in casos.items():
        meta = datos['metadatos']
        fs, N = meta['fs_hz'], meta['n_bloque']
        # Bloque después del fade inicial; el título explicita el origen temporal.
        inicio = max(int(fs * 0.1), int(fs * meta['fade_ms'] / 1000))
        inicio = min(inicio, len(datos['limpia']) - N)
        limites = [0, 1500, 2300, 4000, fs / 2]
        if fs / 2 <= 4000:
            raise ValueError('Estas bandas de caracterización requieren fs > 8000 Hz.')
        fig, axs = plt.subplots(2, 2, figsize=(13, 8))
        vista = min(int(fs * .01), N)
        etiquetas = {'limpia': 'Limpia', 'ruido': 'Ruido', 'contaminada': 'Contaminada'}
        for tipo, color in [('limpia', 'tab:blue'), ('ruido', 'tab:orange'), ('contaminada', 'tab:green')]:
            x = datos[tipo]
            espec = espectro_bloque(x[inicio:inicio + N], fs)
            axs[0, 0].plot(datos['tiempo'][inicio:inicio + vista] * 1000,
                           x[inicio:inicio + vista], label=etiquetas[tipo], color=color, alpha=.75)
            axs[0, 1].plot(espec['frecuencia_hz'], espec['magnitud_db'], label=etiquetas[tipo], color=color)
            # Puntos: no unir fases a través de saltos de +/-pi.
            axs[1, 0].plot(espec['frecuencia_hz'], espec['fase_rad'], '.', ms=2, label=etiquetas[tipo], color=color)
            bandas = energia_por_bandas(x, fs, limites)
            pos = np.arange(len(bandas)) + {'limpia': -.25, 'ruido': 0, 'contaminada': .25}[tipo]
            axs[1, 1].bar(pos, [b['porcentaje'] for b in bandas], width=.25, label=etiquetas[tipo], color=color)
            tabla_energia.extend({'caso': nombre, 'senal': tipo, **b} for b in bandas)
        axs[0, 0].set(xlabel='Tiempo absoluto (ms)', ylabel='Amplitud digital', title='Vista temporal: 10 ms')
        axs[0, 1].set(xlabel='Frecuencia (Hz)', ylabel='Amplitud (dB re 1)', ylim=(-100, 5), title=f'Hann: N={N}, Δf={fs / N:.3f} Hz')
        axs[1, 0].set(xlabel='Frecuencia (Hz)', ylabel='Fase (rad)', ylim=(-3.3, 3.3), title='Fase principal: umbral -60 dB relativo por señal')
        axs[1, 1].set(xlabel='Banda (Hz)', ylabel='Energía de cada señal (%)', title='Registro completo, sin ventana')
        axs[1, 1].set_xticks(np.arange(len(limites) - 1), [f'{a:g}–{b:g}' for a, b in zip(limites[:-1], limites[1:])], rotation=15)
        for ax in axs.flat:
            ax.grid(True, alpha=.25)
            ax.legend(fontsize=8)
        fig.suptitle(f'{nombre} | SNR={meta["snr_obtenida_db"]:.2f} dB | bloque desde t={inicio / fs:.3f} s')
        guardar_figura(fig, figuras / f'{nombre}_caracterizacion.png')
        tabla_resumen.append({'caso': nombre, 'semilla': meta['semilla'], 'fs_hz': fs, 'n_bloque': N,
                              'n_muestras': meta['n_muestras'], 'snr_objetivo_db': meta['snr_objetivo_db'],
                              'snr_obtenida_db': meta['snr_obtenida_db'],
                              'error_simetria_max': error_simetria(datos['contaminada'][inicio:inicio + N])})
    guardar_csv(salida / 'energia_bandas.csv', tabla_energia)
    guardar_csv(salida / 'caracterizacion.csv', tabla_resumen)
    return tabla_resumen


def experimentos_fundamentos(fs=16000, N=1024, salida=None):
    """Ventanas, DFT/FFT, simetría y compromiso bloque/resolución."""
    if N < 256 or N & (N - 1):
        raise ValueError('Use N potencia de dos, al menos 256.')
    salida = Path(salida) if salida else RAIZ / 'resultados'
    figuras = salida / 'figuras'
    figuras.mkdir(parents=True, exist_ok=True)
    t = np.arange(N) / fs
    bin_tono = N // 16
    frecuencias = [bin_tono * fs / N, (bin_tono + .5) * fs / N]
    fig, axs = plt.subplots(2, 2, figsize=(13, 8))
    for columna, f in enumerate(frecuencias):
        x = np.sin(2 * np.pi * f * t)
        for ventana, etiqueta in [('boxcar', 'Rectangular'), ('hann', 'Hann')]:
            e = espectro_bloque(x, fs, ventana)
            axs[0, columna].plot(e['frecuencia_hz'], e['magnitud_db'], '.-', ms=3, label=etiqueta)
            axs[1, columna].plot(e['frecuencia_hz'], e['fase_rad'], '.', ms=4, label=etiqueta)
        for fila in range(2):
            axs[fila, columna].set_xlim(f - 12 * fs / N, f + 12 * fs / N)
            axs[fila, columna].set_xlabel('Frecuencia (Hz)')
            axs[fila, columna].grid(True, alpha=.25)
            axs[fila, columna].legend()
        axs[0, columna].set(title=f'{f:.4f} Hz: {"centrado en bin" if columna == 0 else "entre bins"}', ylabel='Amplitud (dB re 1)', ylim=(-110, 5))
        axs[1, columna].set(ylabel='Fase (rad)', ylim=(-3.3, 3.3))
    fig.suptitle(f'Ventanas: N={N}, fs={fs} Hz. Se muestran bins reales, sin zero-padding')
    guardar_figura(fig, figuras / 'fundamentos_ventanas.png')
    # Una muestra pequeña para la DFT por definición.
    M = 64
    n = np.arange(M)
    x = .7 * np.cos(2 * np.pi * 5 * n / M + .3) + .2 * np.sin(2 * np.pi * 11 * n / M)
    directa, rapida = dft_directa(x), np.fft.fft(x)
    error_dft = float(np.max(np.abs(directa - rapida)))
    # Eliminar solo +k rompe la simetría; eliminar +k y -k la conserva.
    tono = np.cos(2 * np.pi * bin_tono * np.arange(N) / N)
    X = np.fft.fft(tono)
    incorrecto = X.copy()
    incorrecto[bin_tono] = 0
    correcto = incorrecto.copy()
    correcto[-bin_tono] = 0
    yi, yc = np.fft.ifft(incorrecto), np.fft.ifft(correcto)
    fig, axs = plt.subplots(2, 1, figsize=(10, 6))
    for ax, y, titulo in zip(axs, [yi, yc], ['Solo bin positivo eliminado: simetría rota', 'Par conjugado eliminado: simetría conservada']):
        ax.plot(t[:128] * 1000, y.real[:128], label='Parte real')
        ax.plot(t[:128] * 1000, y.imag[:128], label='Parte imaginaria')
        ax.set(xlabel='Tiempo (ms)', ylabel='Amplitud', title=titulo, ylim=(-.6, .6))
        ax.grid(True, alpha=.25)
        ax.legend()
    guardar_figura(fig, figuras / 'fundamentos_simetria.png')
    resumen = {'fs_hz': fs, 'n_bloque': N, 'delta_f_hz': fs / N,
               'duracion_bloque_ms': 1000 * N / fs, 'tono_en_bin_hz': frecuencias[0],
               'tono_entre_bins_hz': frecuencias[1], 'n_dft_directa': M,
               'error_dft_fft_max': error_dft, 'error_simetria_max': error_simetria(tono),
               'imag_ifft_sin_simetria_max': float(np.max(np.abs(yi.imag))),
               'imag_ifft_con_simetria_max': float(np.max(np.abs(yc.imag)))}
    (salida / 'fundamentos.json').write_text(json.dumps(resumen, indent=2), encoding='utf-8')
    guardar_csv(salida / 'resolucion_bloques.csv', [
        {'n_bloque': m, 'delta_f_hz': fs / m, 'adquisicion_bloque_ms': 1000 * m / fs,
         'un_buffer_float32_bytes': 4 * m} for m in (256, 512, 1024, 2048)])
    return resumen


if __name__ == '__main__':
    # Backend sin ventana interactiva: todos los resultados se guardan en disco.
    plt.switch_backend('Agg')
    casos = generar_todos()
    analizar_todos(casos)
    print(json.dumps(experimentos_fundamentos(), indent=2))
    print('Figuras y tablas guardadas en', RAIZ / 'resultados')
