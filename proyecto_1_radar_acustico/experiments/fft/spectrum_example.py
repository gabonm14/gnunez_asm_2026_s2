"""
Experimentos de representación espectral.

Se analizan diferentes señales mediante la FFT implementada
para observar su representación en magnitud y fase.

Proyecto:
    Radar acústico
    CE1110 - Análisis de Señales Mixtas
"""

import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src" / "python"

sys.path.insert(0, str(SRC_PATH))

from fft import fft


# ---------------------------------------------------------
# Parámetros generales
# ---------------------------------------------------------

FS = 48000          # Frecuencia de muestreo [Hz]
N = 2048            # Número de muestras
T = N / FS

t = np.arange(N) / FS


# ---------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------

def calculate_spectrum(signal):
    """
    Calcula el espectro unilateral de una señal utilizando
    la FFT implementada en el proyecto.

    Retorna
    -------
    frequencies : ndarray
        Frecuencias correspondientes a los coeficientes.

    magnitude : ndarray
        Magnitud normalizada del espectro.

    phase : ndarray
        Fase en radianes.
    """

    X = np.array(fft(signal))

    # Solo necesitamos la mitad positiva del espectro
    X_positive = X[:N // 2]

    frequencies = np.arange(N // 2) * FS / N

    magnitude = (2.0 / N) * np.abs(X_positive)

    phase = np.angle(X_positive)

    # La fase de componentes prácticamente inexistentes
    # no tiene significado físico útil.

    phase_threshold = 0.01 * np.max(magnitude)


    return frequencies, magnitude, phase


def save_signal_plot(signal, frequencies, magnitude, phase, name, title):
    """
    Genera y guarda las gráficas temporal, de magnitud y de fase.
    """

    output_dir = PROJECT_ROOT / "results" / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------
    # Señal en el dominio temporal
    # -----------------------------------------------------

    plt.figure()

    # Mostrar solo los primeros 5 ms para facilitar lectura
    samples_to_show = int(0.005 * FS)

    plt.plot(
        t[:samples_to_show] * 1000,
        signal[:samples_to_show]
    )

    plt.xlabel("Tiempo [ms]")
    plt.ylabel("Amplitud")
    plt.title(f"{title} - dominio temporal")
    plt.grid(True)
    plt.tight_layout()

    plt.savefig(
        output_dir / f"{name}_time.png",
        dpi=300
    )

    plt.show()

    # -----------------------------------------------------
    # Magnitud
    # -----------------------------------------------------

    plt.figure()

    plt.plot(
        frequencies,
        magnitude
    )

    plt.xlabel("Frecuencia [Hz]")
    plt.ylabel("Magnitud")
    plt.title(f"{title} - espectro de magnitud")
    plt.grid(True)

    plt.xlim(0, 12000)

    plt.tight_layout()

    plt.savefig(
        output_dir / f"{name}_magnitude.png",
        dpi=300
    )

    plt.show()

    # -----------------------------------------------------
    # Fase
    # -----------------------------------------------------

    plt.figure()

    # Solo se muestra fase en componentes con magnitud
    # suficientemente significativa.
    phase_threshold = 0.01 * np.max(magnitude)

    valid_phase = magnitude > phase_threshold

    frequencies_phase = frequencies[valid_phase]
    phase_values = phase[valid_phase]

    if name == "chirp":

        plt.scatter(
            frequencies_phase,
            phase_values,
            s=10
        )

    else:

        plt.scatter(
            frequencies_phase,
            phase_values
        )

    plt.xlabel("Frecuencia [Hz]")
    plt.ylabel("Fase [rad]")
    plt.title(f"{title} - espectro de fase")
    plt.grid(True)

    plt.xlim(0, 12000)

    plt.tight_layout()

    plt.savefig(
        output_dir / f"{name}_phase.png",
        dpi=300
    )

    plt.show()


# ---------------------------------------------------------
# Experimento 1: senoide pura
# ---------------------------------------------------------

def experiment_single_tone():

    frequency = 3000

    signal = np.sin(
        2 * np.pi * frequency * t
    )

    frequencies, magnitude, phase = calculate_spectrum(signal)

    save_signal_plot(
        signal,
        frequencies,
        magnitude,
        phase,
        "single_tone",
        "Senoide de 3 kHz"
    )


# ---------------------------------------------------------
# Experimento 2: dos frecuencias
# ---------------------------------------------------------

def experiment_two_tones():

    f1 = 3000
    f2 = 6000

    signal = (
        np.sin(2 * np.pi * f1 * t)
        + 0.5 * np.sin(2 * np.pi * f2 * t)
    )

    frequencies, magnitude, phase = calculate_spectrum(signal)

    save_signal_plot(
        signal,
        frequencies,
        magnitude,
        phase,
        "two_tones",
        "Senoides de 3 kHz y 6 kHz"
    )


# ---------------------------------------------------------
# Experimento 3: chirp lineal
# ---------------------------------------------------------

def experiment_chirp():

    f_start = 2000
    f_end = 10000

    chirp_duration = T

    slope = (
        f_end - f_start
    ) / chirp_duration

    phase_chirp = 2 * np.pi * (
        f_start * t
        + 0.5 * slope * t**2
    )

    signal = np.sin(phase_chirp)

    frequencies, magnitude, phase = calculate_spectrum(signal)

    save_signal_plot(
        signal,
        frequencies,
        magnitude,
        phase,
        "chirp",
        "Chirp lineal de 2 kHz a 10 kHz"
    )


# ---------------------------------------------------------
# Programa principal
# ---------------------------------------------------------

if __name__ == "__main__":

    print("Experimento 1: senoide de 3 kHz")
    experiment_single_tone()

    print("Experimento 2: senoides de 3 kHz y 6 kHz")
    experiment_two_tones()

    print("Experimento 3: chirp lineal de 2 kHz a 10 kHz")
    experiment_chirp()

    print("\nExperimentos finalizados.")