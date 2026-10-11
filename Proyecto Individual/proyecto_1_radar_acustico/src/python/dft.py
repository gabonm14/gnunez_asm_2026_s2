"""
Implementación directa de la Transformada Discreta de Fourier (DFT).

Proyecto:
    Radar acústico - CE1110 Análisis de Señales Mixtas

La implementación se realiza directamente a partir de la definición
matemática de la DFT, sin utilizar numpy.fft.
"""

import cmath
import math


def dft(signal):
    """
    Calcula la Transformada Discreta de Fourier de una señal.

    Parámetros
    ----------
    signal : iterable
        Secuencia de muestras reales o complejas.

    Retorna
    -------
    list[complex]
        Coeficientes complejos X[k] de la DFT.
    """

    x = list(signal)
    N = len(x)

    if N == 0:
        return []

    spectrum = []

    for k in range(N):
        X_k = 0j

        for n in range(N):
            angle = -2.0 * math.pi * k * n / N

            twiddle_factor = cmath.exp(1j * angle)

            X_k += x[n] * twiddle_factor

        spectrum.append(X_k)

    return spectrum



def magnitude(spectrum):
    """
    Calcula la magnitud de cada coeficiente complejo.
    """

    return [abs(value) for value in spectrum]


def phase(spectrum):
    """
    Calcula la fase en radianes de cada coeficiente complejo.
    """

    return [cmath.phase(value) for value in spectrum]


if __name__ == "__main__":
    signal = [1, 0, -1, 0]

    spectrum = dft(signal)

    magnitudes = magnitude(spectrum)
    phases = phase(spectrum)

    print("Señal:")
    print(signal)

    print("\nDFT:")

    for k, value in enumerate(spectrum):
        print(
            f"k={k}: "
            f"X[k]={value:.4f}, "
            f"|X[k]|={magnitudes[k]:.4f}, "
            f"fase={phases[k]:.4f} rad"
        )