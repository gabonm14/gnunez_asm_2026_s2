"""
Comparación experimental de tiempos de ejecución entre
la DFT directa y la FFT radix-2.
"""

import sys
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))


from dft import dft
from fft import fft


def measure_time(function, signal, repetitions=3):
    """
    Mide el tiempo promedio de ejecución de una función.
    """

    total_time = 0.0

    for _ in range(repetitions):

        start = time.perf_counter()

        function(signal)

        end = time.perf_counter()

        total_time += end - start

    return total_time / repetitions


def main():

    sizes = [
        16,
        32,
        64,
        128,
        256,
        512,
        1024
    ]

    dft_times = []
    fft_times = []

    for N in sizes:

        signal = np.random.random(N)

        dft_time = measure_time(dft, signal)
        fft_time = measure_time(fft, signal)

        dft_times.append(dft_time)
        fft_times.append(fft_time)

        print(
            f"N = {N:4d} | "
            f"DFT = {dft_time:.6f} s | "
            f"FFT = {fft_time:.6f} s"
        )

    plt.figure()

    plt.plot(
        sizes,
        dft_times,
        marker="o",
        label="DFT directa"
    )

    plt.plot(
        sizes,
        fft_times,
        marker="o",
        label="FFT radix-2"
    )

    plt.xlabel("Número de muestras N")
    plt.ylabel("Tiempo de ejecución [s]")
    plt.title("Comparación de tiempo de ejecución: DFT vs FFT")

    plt.grid(True)
    plt.legend()

    plt.tight_layout()

    output_path = (
        PROJECT_ROOT
        / "results"
        / "figures"
        / "dft_vs_fft_time.png"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    plt.savefig(
        output_path,
        dpi=300
    )

    plt.show()


if __name__ == "__main__":
    main()