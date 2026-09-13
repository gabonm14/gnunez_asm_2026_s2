"""
Pruebas para los algoritmos de correlación.
"""

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from correlation import cross_correlation_direct


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


if __name__ == "__main__":

    test_known_delay()

    print(
        "Prueba de correlacion directa superada correctamente."
    )