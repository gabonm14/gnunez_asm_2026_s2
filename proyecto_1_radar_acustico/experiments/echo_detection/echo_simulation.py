"""
Simulación de una señal acústica transmitida y sus ecos.

Se genera un chirp conocido y una señal recibida que contiene:

- señal directa;
- eco principal;
- reflexión secundaria;
- ruido.

Los retardos utilizados son conocidos para permitir posteriormente
la validación de los algoritmos de correlación.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------
# Importación de módulos del proyecto
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from signals import linear_chirp


# ---------------------------------------------------------
# Parámetros
# ---------------------------------------------------------

FS = 48000

CHIRP_DURATION = 0.010

F_START = 2000
F_END = 10000

# Valor provisional utilizado solamente en simulación.
SPEED_OF_SOUND = 343.0

# Distancia conocida utilizada para generar el eco principal.
TARGET_DISTANCE = 1.0

# Duración total de la adquisición simulada.
RECORDING_DURATION = 0.050


# ---------------------------------------------------------
# Funciones
# ---------------------------------------------------------

def distance_to_delay(distance, speed_of_sound, fs):
    """
    Convierte una distancia monostática en tiempo de vuelo
    y posteriormente en cantidad de muestras.

    Retorna
    -------
    delay_seconds : float
        Tiempo de vuelo [s].

    delay_samples : int
        Retardo equivalente en muestras.
    """

    delay_seconds = (2.0 * distance) / speed_of_sound

    delay_samples = int(
        round(delay_seconds * fs)
    )

    return delay_seconds, delay_samples


def add_delayed_signal(destination, signal, delay_samples, amplitude):
    """
    Añade una copia retardada y escalada de una señal
    dentro de un vector de destino.
    """

    start = delay_samples
    end = start + len(signal)

    if end > len(destination):
        raise ValueError(
            "La señal retardada no cabe dentro de la "
            "duración total de adquisición."
        )

    destination[start:end] += amplitude * signal


# ---------------------------------------------------------
# Programa principal
# ---------------------------------------------------------

def main():

    # Generar chirp transmitido
    chirp_time, transmitted = linear_chirp(
        FS,
        CHIRP_DURATION,
        F_START,
        F_END
    )

    # Número total de muestras de la adquisición
    total_samples = int(
        FS * RECORDING_DURATION
    )

    received = np.zeros(total_samples)

    # -----------------------------------------------------
    # Señal directa
    # -----------------------------------------------------

    add_delayed_signal(
        received,
        transmitted,
        delay_samples=0,
        amplitude=0.6
    )

    # -----------------------------------------------------
    # Eco principal
    # -----------------------------------------------------

    echo_delay_seconds, echo_delay_samples = distance_to_delay(
        TARGET_DISTANCE,
        SPEED_OF_SOUND,
        FS
    )

    add_delayed_signal(
        received,
        transmitted,
        delay_samples=echo_delay_samples,
        amplitude=0.8
    )

    # -----------------------------------------------------
    # Reflexión secundaria
    # -----------------------------------------------------

    secondary_distance = 2.2

    _, secondary_delay_samples = distance_to_delay(
        secondary_distance,
        SPEED_OF_SOUND,
        FS
    )

    add_delayed_signal(
        received,
        transmitted,
        delay_samples=secondary_delay_samples,
        amplitude=0.3
    )

    # -----------------------------------------------------
    # Ruido
    # -----------------------------------------------------

    rng = np.random.default_rng(seed=42)

    noise = rng.normal(
        loc=0.0,
        scale=0.05,
        size=total_samples
    )

    received += noise



    

    # -----------------------------------------------------
    # Información del experimento
    # -----------------------------------------------------

    print("=== Simulación de ecos ===")

    print(
        f"Frecuencia de muestreo: {FS} Hz"
    )

    print(
        f"Distancia objetivo: {TARGET_DISTANCE:.3f} m"
    )

    print(
        f"Retardo esperado: {echo_delay_seconds * 1000:.3f} ms"
    )

    print(
        f"Retardo esperado: {echo_delay_samples} muestras"
    )

    print(
        f"Distancia secundaria: {secondary_distance:.3f} m"
    )

    print(
        f"Retardo secundario: {secondary_delay_samples} muestras"
    )

    # -----------------------------------------------------
    # Gráfica
    # -----------------------------------------------------

    time_received = (
        np.arange(total_samples) / FS
    )

    plt.figure()

    plt.plot(
        time_received * 1000,
        received,
        label="Señal recibida"
    )

    plt.xlabel("Tiempo [ms]")
    plt.ylabel("Amplitud")

    plt.title(
        "Simulación de señal directa y ecos"
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
        output_dir / "echo_simulation.png",
        dpi=300
    )

    plt.show()



    # -----------------------------------------------------
    # Guardar datos simulados
    # -----------------------------------------------------

    data_dir = (
        PROJECT_ROOT
        / "data"
        / "simulated"
    )

    data_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    np.savez(
        data_dir / "echo_scene.npz",
        transmitted=transmitted,
        received=received,
        fs=FS,
        speed_of_sound=SPEED_OF_SOUND,
        target_distance=TARGET_DISTANCE,
        expected_delay_samples=echo_delay_samples,
        secondary_distance=secondary_distance,
        secondary_delay_samples=secondary_delay_samples
    )


if __name__ == "__main__":
    main()