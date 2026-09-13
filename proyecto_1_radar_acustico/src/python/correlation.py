"""
Algoritmos de correlación utilizados para detección de ecos.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import numpy as np


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