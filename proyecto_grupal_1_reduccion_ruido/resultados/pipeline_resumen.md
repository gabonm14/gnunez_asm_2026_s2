# Pipeline end-to-end

Referencia: la señal que entrega el emisor. Mejora separada = independiente del retardo.

| Caso | Método | MSE | Mejora alineada (dB) | Mejora separada (dB) | Energía útil (%) | Latencia (ms) | Criterio |
|---|---|---:|---:|---:|---:|---:|---|
| caso_1 | sin_filtrar | 0.04907 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_1 | FIR | 2.919e-06 | 42.26 | 67.94 | 99.99 | 2.50 | cumple |
| caso_1 | IIR | 0.002967 | 12.18 | 70.08 | 100.00 | 1.34 | cumple |
| caso_1 | espectral_fijo | 3.537e-06 | 41.42 | 59.90 | 99.99 | 64.00 | cumple |
| caso_1 | espectral_adaptativo | 3.563e-06 | 41.39 | 59.90 | 99.99 | 64.00 | cumple |
| caso_2 | sin_filtrar | 0.01703 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_2 | FIR | 2.948e-06 | 37.62 | 65.47 | 99.98 | 2.50 | cumple |
| caso_2 | IIR | 0.001035 | 12.16 | 66.17 | 99.99 | 1.34 | cumple |
| caso_2 | espectral_fijo | 3.337e-06 | 37.08 | 63.62 | 99.98 | 64.00 | cumple |
| caso_2 | espectral_adaptativo | 3.36e-06 | 37.05 | 63.63 | 99.98 | 64.00 | cumple |
| caso_3 | sin_filtrar | 0.01803 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_3 | FIR | 0.01724 | 0.20 | 0.20 | 99.98 | 2.50 | no_cumple |
| caso_3 | IIR | 0.01627 | 0.45 | 0.75 | 99.99 | 1.34 | no_cumple |
| caso_3 | espectral_fijo | 0.006403 | 4.50 | 4.63 | 96.48 | 64.00 | cumple |
| caso_3 | espectral_adaptativo | 0.006403 | 4.50 | 4.63 | 96.48 | 64.00 | cumple |
| caso_5 | sin_filtrar | 0.004589 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_5 | FIR | 2.885e-05 | 22.02 | 28.45 | 99.51 | 2.50 | cumple |
| caso_5 | IIR | 0.0002172 | 13.25 | 40.48 | 99.21 | 1.34 | cumple |
| caso_5 | espectral_fijo | 0.0001366 | 15.26 | 33.13 | 93.57 | 64.00 | no_cumple |
| caso_5 | espectral_adaptativo | 0.0001366 | 15.26 | 33.13 | 93.57 | 64.00 | no_cumple |
| caso_6 | sin_filtrar | 0.0001567 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_6 | FIR | 3.572e-05 | 6.42 | 6.44 | 99.91 | 2.50 | no_cumple |
| caso_6 | IIR | 3.273e-05 | 6.80 | 6.86 | 99.90 | 1.34 | no_cumple |
| caso_6 | espectral_fijo | 1.856e-05 | 9.27 | 9.58 | 97.49 | 64.00 | no_cumple |
| caso_6 | espectral_adaptativo | 1.856e-05 | 9.27 | 9.58 | 97.49 | 64.00 | no_cumple |
| caso_7 | sin_filtrar | 0.06257 | 0.00 | 0.00 | 100.00 | 0.00 | referencia |
| caso_7 | FIR | 3.167e-06 | 42.96 | 69.18 | 100.00 | 2.50 | cumple |
| caso_7 | IIR | 0.0001966 | 25.03 | 71.01 | 100.00 | 1.34 | cumple |
| caso_7 | espectral_fijo | 3.31e-06 | 42.77 | 59.91 | 100.00 | 64.00 | cumple |
| caso_7 | espectral_adaptativo | 3.763e-06 | 42.21 | 59.96 | 100.00 | 64.00 | cumple |
