"""
Pruebas para los algoritmos de correlación.
"""

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from correlation import (
    cross_correlation_direct,
    cross_correlation_fft
)


def test_known_delay():
    """
    Comprueba que la correlación encuentre un retardo
    conocido de dos muestras.
    """

    reference = np.array([
        1.0,
        2.0,
        1.0
    ])

    received = np.array([
        0.0,
        0.0,
        1.0,
        2.0,
        1.0,
        0.0,
        0.0
    ])

    correlation = cross_correlation_direct(
        reference,
        received
    )

    detected_delay = int(
        np.argmax(correlation)
    )

    assert detected_delay == 2



def test_fft_correlation_known_delay():
    """
    Comprueba que la correlación mediante FFT detecte
    correctamente un retardo conocido.
    """

    reference = np.array([
        1.0,
        2.0,
        1.0
    ])

    received = np.array([
        0.0,
        0.0,
        1.0,
        2.0,
        1.0,
        0.0,
        0.0
    ])

    correlation = cross_correlation_fft(
        reference,
        received
    )

    detected_delay = int(
        np.argmax(correlation)
    )

    assert detected_delay == 2


def test_direct_and_fft_match():
    """
    Comprueba que las implementaciones directa y mediante
    FFT produzcan resultados equivalentes.
    """

    reference = np.array([
        1.0,
        0.5,
        -1.0,
        0.25
    ])

    received = np.array([
        0.0,
        0.0,
        1.0,
        0.5,
        -1.0,
        0.25,
        0.0,
        0.0
    ])

    direct_result = cross_correlation_direct(
        reference,
        received
    )

    fft_result = cross_correlation_fft(
        reference,
        received
    )

    assert np.allclose(
        direct_result,
        fft_result,
        atol=1e-10
    )


if __name__ == "__main__":

    test_known_delay()
    test_fft_correlation_known_delay()
    test_direct_and_fft_match()

    print(
        "Prueba de correlacion directa superada correctamente."
    )