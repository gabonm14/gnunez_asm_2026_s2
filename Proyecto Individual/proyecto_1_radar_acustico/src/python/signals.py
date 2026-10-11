"""
Funciones para generación de señales utilizadas en el radar acústico.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import numpy as np


def linear_chirp(fs, duration, f_start, f_end):
    """
    Genera un chirp lineal.

    Parámetros
    ----------
    fs : float
        Frecuencia de muestreo [Hz].

    duration : float
        Duración del chirp [s].

    f_start : float
        Frecuencia inicial [Hz].

    f_end : float
        Frecuencia final [Hz].

    Retorna
    -------
    t : ndarray
        Vector de tiempo.

    signal : ndarray
        Muestras del chirp.
    """

    N = int(round(fs * duration))

    t = np.arange(N) / fs

    slope = (f_end - f_start) / duration

    phase = 2.0 * np.pi * (
        f_start * t
        + 0.5 * slope * t**2
    )

    signal = np.sin(phase)

    return t, signal