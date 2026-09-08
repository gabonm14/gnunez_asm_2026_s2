"""
Pruebas para la implementación de la FFT.
"""

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))


from fft import fft


def test_fft_against_numpy():
    """
    Compara nuestra FFT contra numpy.fft.fft.
    """

    signal = [1, 0, -1, 0]

    result = np.array(fft(signal))
    reference = np.fft.fft(signal)

    assert np.allclose(result, reference)


def test_fft_larger_signal():
    """
    Verifica una señal de ocho muestras.
    """

    signal = [1, 2, 3, 4, 4, 3, 2, 1]

    result = np.array(fft(signal))
    reference = np.fft.fft(signal)

    assert np.allclose(result, reference)


def test_invalid_length():
    """
    Comprueba que la implementación rechace tamaños
    que no sean potencia de dos.
    """

    signal = [1, 2, 3]

    try:
        fft(signal)

    except ValueError:
        return

    raise AssertionError(
        "La FFT debería rechazar N que no sea potencia de 2."
    )


if __name__ == "__main__":

    test_fft_against_numpy()
    test_fft_larger_signal()
    test_invalid_length()

    print("Todas las pruebas de FFT fueron superadas.")