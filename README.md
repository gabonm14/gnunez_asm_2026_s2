# gnunez_asm_2026_s2
sistema de radar acústico para estimación de distancia
# CE1110 - Análisis de Señales Mixtas

Repositorio correspondiente al curso CE1110 - Análisis de Señales Mixtas,
II semestre de 2026.

## Proyecto 1 - Radar acústico

El proyecto consiste en el diseño e implementación de un sistema de radar
acústico capaz de detectar un objeto y estimar su distancia mediante el
análisis del eco producido por una señal acústica conocida.

El sistema contempla las siguientes etapas:

1. Generación de una señal acústica conocida.
2. Transmisión mediante un parlante o transductor.
3. Adquisición de la señal recibida mediante un micrófono y ADC.
4. Análisis espectral utilizando DFT y FFT.
5. Detección del eco mediante correlación.
6. Estimación del tiempo de vuelo.
7. Cálculo de la distancia al objeto.
8. Visualización del resultado.

## Estructura del proyecto

```text
proyecto_1_radar_acustico/
├── src/
│   └── python/          Implementaciones de procesamiento de señales
├── tests/               Pruebas de los algoritmos
├── experiments/         Experimentos de DFT, FFT y detección de ecos
├── results/             Figuras y resultados generados
├── data/                Señales simuladas y mediciones reales
├── hardware/            Información del montaje físico
└── docs/                Documentación en LaTeX