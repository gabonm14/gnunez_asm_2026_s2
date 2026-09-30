"""
Comparación de tiempos de ejecución entre la correlación directa
y la correlación implementada mediante FFT.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from correlation import (
    cross_correlation_direct,
    cross_correlation_fft
)

from signals import linear_chirp


# ---------------------------------------------------------
# Parámetros
# ---------------------------------------------------------

FS = 48000

CHIRP_DURATION = 0.010

F_START = 2000
F_END = 10000

DELAY_SAMPLES = 300


# ---------------------------------------------------------
# Medición de tiempo
# ---------------------------------------------------------

def measure_time(function, reference, received, repetitions=3):
    """
    Mide el tiempo promedio de ejecución de una función
    de correlación.
    """

    total_time = 0.0

    for _ in range(repetitions):

        start = time.perf_counter()

        function(
            reference,
            received
        )

        end = time.perf_counter()

        total_time += (
            end - start
        )

    return (
        total_time / repetitions
    )


# ---------------------------------------------------------
# Generación de señal de prueba
# ---------------------------------------------------------

def create_received_signal(reference, total_samples, delay_samples):
    """
    Genera una señal recibida con un eco conocido y ruido.
    """

    if (
        delay_samples + len(reference)
        > total_samples
    ):
        raise ValueError(
            "La señal recibida es demasiado corta "
            "para contener el eco."
        )

    rng = np.random.default_rng(
        seed=42
    )

    received = rng.normal(
        loc=0.0,
        scale=0.05,
        size=total_samples
    )

    # Señal directa
    received[
        :len(reference)
    ] += 0.6 * reference

    # Eco
    received[
        delay_samples:
        delay_samples + len(reference)
    ] += 0.8 * reference

    return received


# ---------------------------------------------------------
# Programa principal
# ---------------------------------------------------------

def main():

    _, reference = linear_chirp(
        FS,
        CHIRP_DURATION,
        F_START,
        F_END
    )

    sizes = [
        1024,
        2048,
        4096,
        8192,
        16384
    ]

    direct_times = []
    fft_times = []

    print(
        "=== Benchmark de correlacion ==="
    )

    for N in sizes:

        received = create_received_signal(
            reference,
            N,
            DELAY_SAMPLES
        )

        direct_time = measure_time(
            cross_correlation_direct,
            reference,
            received
        )

        fft_time = measure_time(
            cross_correlation_fft,
            reference,
            received
        )

        direct_times.append(
            direct_time
        )

        fft_times.append(
            fft_time
        )

        # Verificar que ambas detectan lo mismo.
        direct_result = (
            cross_correlation_direct(
                reference,
                received
            )
        )

        fft_result = (
            cross_correlation_fft(
                reference,
                received
            )
        )

        direct_delay = int(
            np.argmax(direct_result)
        )

        fft_delay = int(
            np.argmax(fft_result)
        )

        speedup = (
            direct_time / fft_time
        )

        print(
            f"N = {N:5d} | "
            f"Directa = {direct_time:.6f} s | "
            f"FFT = {fft_time:.6f} s | "
            f"Aceleracion = {speedup:.2f}x | "
            f"lags = {direct_delay}/{fft_delay}"
        )

    # -----------------------------------------------------
    # Gráfica
    # -----------------------------------------------------

    plt.figure()

    plt.plot(
        sizes,
        direct_times,
        marker="o",
        label="Correlación directa"
    )

    plt.plot(
        sizes,
        fft_times,
        marker="o",
        label="Correlación mediante FFT"
    )

    plt.xlabel(
        "Número de muestras de la señal recibida"
    )

    plt.ylabel(
        "Tiempo de ejecución [s]"
    )

    plt.title(
        "Comparación de tiempo: correlación directa vs FFT"
    )

    plt.grid(True)

    plt.legend()

    plt.tight_layout()

    output_dir = (
        PROJECT_ROOT
        / "results"
        / "figures"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    plt.savefig(
        output_dir
        / "correlation_benchmark.png",
        dpi=300
    )

    plt.show()


if __name__ == "__main__":
    main()