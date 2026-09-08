"""
Pruebas para la implementación de la DFT.
"""

import sys
from pathlib import Path

import numpy as np

# Permite importar los módulos ubicados en src/python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from dft import dft


def test_dft_against_numpy():
    """
    Compara la DFT implementada manualmente con numpy.fft.fft.
    """

    signal = [1, 0, -1, 0]

    result = np.array(dft(signal))
    reference = np.fft.fft(signal)

    assert np.allclose(result, reference)


if __name__ == "__main__":
    test_dft_against_numpy()
    print("Prueba DFT superada correctamente.")