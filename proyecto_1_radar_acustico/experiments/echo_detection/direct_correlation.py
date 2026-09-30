"""
Detección de un eco mediante correlación directa.

Se utiliza la escena simulada previamente para estimar
el retardo y posteriormente la distancia al objeto.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from correlation import cross_correlation_direct


# ---------------------------------------------------------
# Parámetros
# ---------------------------------------------------------

# Distancia mínima que consideraremos como posible objeto.
# Esto evita confundir la transmisión directa con un eco.

MIN_DISTANCE = 0.20


# ---------------------------------------------------------
# Programa principal
# ---------------------------------------------------------

def main():

    # -----------------------------------------------------
    # Cargar escena simulada
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
    # Correlación directa
    # -----------------------------------------------------

    correlation = cross_correlation_direct(
        transmitted,
        received
    )

    # -----------------------------------------------------
    # Ignorar región correspondiente a señal directa
    # -----------------------------------------------------

    minimum_lag = int(
        round(
            (2.0 * MIN_DISTANCE / speed_of_sound)
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
    # Convertir retardo a tiempo
    # -----------------------------------------------------

    delay_seconds = (
        detected_delay / fs
    )

    # -----------------------------------------------------
    # Convertir tiempo a distancia
    # -----------------------------------------------------

    estimated_distance = (
        speed_of_sound
        * delay_seconds
        / 2.0
    )

    # -----------------------------------------------------
    # Mostrar resultados
    # -----------------------------------------------------

    print(
        "=== Correlacion directa ==="
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

    error = abs(
        estimated_distance
        - expected_distance
    )

    print(
        f"Error absoluto: {error:.6f} m"
    )

    # -----------------------------------------------------
    # Gráfica de correlación
    # -----------------------------------------------------

    lags = np.arange(
        len(correlation)
    )

    delay_ms = (
        lags / fs
    ) * 1000

    plt.figure()

    plt.plot(
        delay_ms,
        correlation,
        label="Correlación"
    )

    detected_time_ms = (
        detected_delay / fs
    ) * 1000

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
        "Detección de eco mediante correlación directa"
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
        / "direct_correlation.png",
        dpi=300
    )

    plt.show()


if __name__ == "__main__":
    main()