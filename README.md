# CE1110 - Análisis de Señales Mixtas

Repositorio correspondiente al curso **CE1110 - Análisis de Señales Mixtas**, II semestre de 2026.

## Proyecto 1 - Radar acústico

El proyecto consiste en el diseño e implementación de un sistema de radar acústico capaz de detectar un objeto y estimar su distancia mediante el análisis del eco producido por una señal acústica conocida.

El sistema contempla las siguientes etapas:

1. Generación de una señal acústica conocida.
2. Transmisión mediante un parlante o transductor.
3. Adquisición de la señal recibida mediante un micrófono y ADC.
4. Análisis espectral mediante DFT y FFT.
5. Detección del eco mediante correlación.
6. Estimación del tiempo de vuelo.
7. Cálculo de la distancia al objeto.
8. Visualización del resultado.

## Estructura del proyecto

```text
proyecto_1_radar_acustico/
├── src/
│   ├── python/
│   └── firmware/
├── tests/
├── experiments/
│   ├── fft/
│   └── echo_detection/
├── data/
│   ├── simulated/
│   └── measured/
├── results/
│   ├── figures/
│   └── tables/
├── hardware/
└── docs/
    ├── taller_semana5/
    ├── paper/
    └── herramientas_ingenieria/
```

## Herramientas

Durante el desarrollo del proyecto se utilizarán principalmente:

- Python 3
- NumPy
- Matplotlib
- Git
- GitHub
- Visual Studio Code
- LaTeX
- Overleaf

Las herramientas asociadas al microcontrolador se definirán una vez seleccionado el hardware final.

## Flujo de trabajo con Git

El repositorio utiliza dos ramas principales:

- `master`: contiene versiones estables del proyecto.
- `development`: contiene el trabajo integrado en desarrollo.

Las nuevas funcionalidades se realizan en ramas independientes creadas a partir de `development`.

Algunos ejemplos de ramas de trabajo son:

- `feature/dft`
- `feature/fft`
- `feature/echo-simulation`
- `feature/correlation`
- `hardware/acquisition`
- `firmware/signal-generation`
- `docs/taller-semana5`

Una vez finalizada y verificada una funcionalidad, su rama se fusiona nuevamente con `development`.

Cuando una versión completa del proyecto se encuentra estable, `development` se fusiona con `master`.

## Autores

- Gabriel Bolaños Barboza
- Gabriel Núñez Morales