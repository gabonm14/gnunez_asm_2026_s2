"""
Detección de eco mediante correlación calculada con FFT.

Se utiliza la misma escena simulada empleada para la
correlación directa.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from correlation import cross_correlation_fft


MIN_DISTANCE = 0.20


def main():

    # -----------------------------------------------------
    # Cargar escena
    # -----------------------------------------------------

    data_path = (
        PROJECT_ROOT
        / "data"
        / "simulated"
        / "echo_scene.npz"
    )

    data = np.load(data_path)

    transmitted = data["transmitted"]
    received = data["received"]

    fs = float(data["fs"])

    speed_of_sound = float(
        data["speed_of_sound"]
    )

    expected_delay = int(
        data["expected_delay_samples"]
    )

    expected_distance = float(
        data["target_distance"]
    )

    # -----------------------------------------------------
    # Correlación mediante FFT
    # -----------------------------------------------------

    correlation = cross_correlation_fft(
        transmitted,
        received
    )

    # -----------------------------------------------------
    # Ignorar señal directa
    # -----------------------------------------------------

    minimum_lag = int(
        round(
            (
                2.0
                * MIN_DISTANCE
                / speed_of_sound
            )
            * fs
        )
    )

    detected_delay = (
        np.argmax(
            correlation[minimum_lag:]
        )
        + minimum_lag
    )

    # -----------------------------------------------------
    # Retardo y distancia
    # -----------------------------------------------------

    delay_seconds = (
        detected_delay / fs
    )

    estimated_distance = (
        speed_of_sound
        * delay_seconds
        / 2.0
    )

    error = abs(
        estimated_distance
        - expected_distance
    )

    # -----------------------------------------------------
    # Resultados
    # -----------------------------------------------------

    print(
        "=== Correlacion mediante FFT ==="
    )

    print(
        f"Retardo esperado: {expected_delay} muestras"
    )

    print(
        f"Retardo detectado: {detected_delay} muestras"
    )

    print(
        f"Distancia esperada: {expected_distance:.4f} m"
    )

    print(
        f"Distancia estimada: {estimated_distance:.4f} m"
    )

    print(
        f"Error absoluto: {error:.6f} m"
    )

    # -----------------------------------------------------
    # Gráfica
    # -----------------------------------------------------

    lags = np.arange(
        len(correlation)
    )

    delay_ms = (
        lags / fs
    ) * 1000

    detected_time_ms = (
        detected_delay / fs
    ) * 1000

    plt.figure()

    plt.plot(
        delay_ms,
        correlation,
        label="Correlación mediante FFT"
    )

    plt.axvline(
        detected_time_ms,
        linestyle="--",
        label="Eco detectado"
    )

    plt.xlabel(
        "Retardo [ms]"
    )

    plt.ylabel(
        "Correlación"
    )

    plt.title(
        "Detección de eco mediante correlación FFT"
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
        / "fft_correlation.png",
        dpi=300
    )

    plt.show()


if __name__ == "__main__":
    main()