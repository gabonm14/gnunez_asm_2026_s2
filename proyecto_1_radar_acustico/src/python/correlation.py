"""
Algoritmos de correlación utilizados para detección de ecos.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import numpy as np

from fft import fft, ifft


def cross_correlation_direct(reference, received):
    """
    Calcula directamente la correlación cruzada entre una
    señal de referencia y una señal recibida.

    Solo se consideran retardos no negativos, ya que en el
    radar acústico el eco ocurre después de la transmisión.

    Parámetros
    ----------
    reference : iterable
        Señal conocida transmitida.

    received : iterable
        Señal adquirida por el receptor.

    Retorna
    -------
    ndarray
        Valor de correlación para cada retardo posible.
    """

    x = np.asarray(reference, dtype=float)
    y = np.asarray(received, dtype=float)

    if len(x) == 0 or len(y) == 0:
        raise ValueError(
            "Las señales no pueden estar vacías."
        )

    if len(y) < len(x):
        raise ValueError(
            "La señal recibida debe ser al menos tan larga "
            "como la señal de referencia."
        )

    number_of_lags = len(y) - len(x) + 1

    correlation = np.zeros(number_of_lags)

    for lag in range(number_of_lags):

        accumulator = 0.0

        for n in range(len(x)):

            accumulator += (
                x[n]
                * y[n + lag]
            )

        correlation[lag] = accumulator

    return correlation

def next_power_of_two(value):
    """
    Retorna la potencia de dos más pequeña que sea
    mayor o igual al valor indicado.
    """

    power = 1

    while power < value:
        power *= 2

    return power


def cross_correlation_fft(reference, received):
    """
    Calcula la correlación cruzada mediante FFT.

    La correlación se obtiene como una convolución entre
    la señal recibida y la referencia invertida.

    Se utiliza zero padding para obtener una convolución
    lineal y evitar efectos de convolución circular.

    Parámetros
    ----------
    reference : iterable
        Señal conocida transmitida.

    received : iterable
        Señal recibida.

    Retorna
    -------
    ndarray
        Correlación para retardos no negativos.
    """

    x = np.asarray(
        reference,
        dtype=float
    )

    y = np.asarray(
        received,
        dtype=float
    )

    if len(x) == 0 or len(y) == 0:
        raise ValueError(
            "Las señales no pueden estar vacías."
        )

    if len(y) < len(x):
        raise ValueError(
            "La señal recibida debe ser al menos tan larga "
            "como la señal de referencia."
        )

    # Longitud necesaria para convolución lineal.
    convolution_length = (
        len(x)
        + len(y)
        - 1
    )

    # Nuestra FFT radix-2 necesita una potencia de dos.
    fft_length = next_power_of_two(
        convolution_length
    )

    # Invertir la referencia para convertir
    # correlación en convolución.
    reversed_reference = x[::-1]

    # Zero padding.
    padded_reference = np.zeros(
        fft_length
    )

    padded_received = np.zeros(
        fft_length
    )

    padded_reference[
        :len(reversed_reference)
    ] = reversed_reference

    padded_received[
        :len(y)
    ] = y

    # FFT de ambas señales.
    X = fft(padded_reference)
    Y = fft(padded_received)

    # Multiplicación en frecuencia.
    product = [
        X[k] * Y[k]
        for k in range(fft_length)
    ]

    # Regresar al dominio temporal.
    convolution = np.array(
        ifft(product)
    ).real

    # La correlación para lag = 0 comienza en
    # el índice len(reference) - 1.
    start = len(x) - 1

    number_of_lags = (
        len(y)
        - len(x)
        + 1
    )

    end = start + number_of_lags

    correlation = convolution[
        start:end
    ]

    return correlation