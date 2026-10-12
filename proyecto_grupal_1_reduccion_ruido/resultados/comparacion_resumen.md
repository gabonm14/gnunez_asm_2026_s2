# Comparación automática

Mismo intervalo de referencia para entrada, FIR y espectral.

| Caso | Método | MSE | SNR salida (dB) | Mejora (dB) | Energía útil (%) | Criterio |
|---|---|---:|---:|---:|---:|---|
| caso_1 | sin_filtrar | 0.0490732 | 2.018 | 0.000 | 100.000 | referencia |
| caso_1 | FIR | 5.02878e-09 | 71.912 | 69.894 | 99.994 | cumple |
| caso_1 | espectral | 5.70857e-08 | 61.361 | 59.343 | 99.999 | cumple |
| caso_2 | sin_filtrar | 0.017025 | 2.013 | 0.000 | 100.000 | referencia |
| caso_2 | FIR | 8.13402e-10 | 75.220 | 73.208 | 99.994 | cumple |
| caso_2 | espectral | 7.21391e-09 | 65.742 | 63.729 | 100.000 | cumple |
| caso_3 | sin_filtrar | 0.0180299 | 2.010 | 0.000 | 100.000 | referencia |
| caso_3 | FIR | 0.0172328 | 2.207 | 0.196 | 99.994 | no_cumple |
| caso_3 | espectral | 0.00640009 | 6.508 | 4.498 | 96.420 | cumple |

## Interpretación y límites

En los casos separados, compare MSE y SNR para determinar qué salida se aproxima más a la referencia. En superposición, compare además distorsión y energía útil: reducir ruido puede eliminar componentes útiles.
La energía de salida total no equivale a energía útil conservada. Las componentes de evaluación del método espectral usan las máscaras aprendidas desde la mezcla.
FIR se compensa 40 muestras en este diseño. La salida espectral es una referencia offline alineada. Esta comparación de calidad no elimina ni mide las latencias físicas.
Los tiempos se miden de nuevo en cada máquina y ejecución. La RAM estimada no es una medición del consumo de Python ni del firmware.
Para el artículo se deben explicar resultados y fallos, no copiar solo esta tabla. La propuesta de placa y comunicación sigue pendiente.
