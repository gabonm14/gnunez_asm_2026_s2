"""
Implementación de la Transformada Rápida de Fourier (FFT).

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas

Se implementa el algoritmo radix-2 de Cooley-Tukey sin utilizar
numpy.fft para realizar el cálculo principal.
"""

import cmath
import math


def fft(signal):
    """
    Calcula la Transformada Rápida de Fourier mediante
    el algoritmo radix-2 de Cooley-Tukey.

    Parámetros
    ----------
    signal : iterable
        Secuencia de muestras reales o complejas.

    Retorna
    -------
    list[complex]
        Coeficientes complejos de la FFT.

    Raises
    ------
    ValueError
        Si la cantidad de muestras no es una potencia de 2.
    """

    x = list(signal)
    N = len(x)

    if N == 0:
        return []

    if N == 1:
        return [complex(x[0])]

    if N & (N - 1) != 0:
        raise ValueError(
            "La FFT radix-2 requiere que N sea una potencia de 2."
        )

    # Separar muestras de índice par e impar
    even = fft(x[0::2])
    odd = fft(x[1::2])

    spectrum = [0j] * N

    for k in range(N // 2):

        twiddle_factor = cmath.exp(
            -2j * math.pi * k / N
        )

        t = twiddle_factor * odd[k]

        spectrum[k] = even[k] + t
        spectrum[k + N // 2] = even[k] - t

    return spectrum



def ifft(spectrum):
    """
    Calcula la Transformada Inversa Rápida de Fourier (IFFT)
    utilizando la FFT implementada en el proyecto.

    Se utiliza la propiedad:

        IFFT(X) = conjugado(FFT(conjugado(X))) / N

    Parámetros
    ----------
    spectrum : iterable
        Coeficientes complejos en el dominio de frecuencia.

    Retorna
    -------
    list[complex]
        Señal reconstruida en el dominio temporal.
    """

    X = list(spectrum)
    N = len(X)

    if N == 0:
        return []

    conjugated = [
        value.conjugate()
        for value in X
    ]

    transformed = fft(conjugated)

    result = [
        value.conjugate() / N
        for value in transformed
    ]

    return result


if __name__ == "__main__":

    signal = [1, 0, -1, 0]

    spectrum = fft(signal)

    print("Señal:")
    print(signal)

    print("\nResultado de la FFT:")

    for k, value in enumerate(spectrum):
        print(f"X[{k}] = {value:.4f}")