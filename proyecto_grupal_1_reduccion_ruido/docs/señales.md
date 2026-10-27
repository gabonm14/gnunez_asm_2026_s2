# Señales y ruidos de prueba

Configuración en `metadatos/configuraciones.json`. Se regenera con `python -m src.generacion`.
Cada caso se guarda en `pruebas/caso_X/`:

| Archivo | Contenido |
|---|---|
| `limpia.wav` | Señal útil |
| `ruido.wav` | Ruido aislado |
| `contaminada.wav` | Mezcla de señal útil y ruido |
| `muestras.npz` | Referencias exactas en float64, usadas para las métricas |
| `metadatos.json` | Parámetros del caso |

## Parámetros generales

| Parámetro | Valor | Justificación |
|---|---|---|
| Frecuencia de muestreo fs | 16 000 Hz | Nyquist = 8000 Hz, por encima de todas las componentes |
| Duración | 6 s (96 000 muestras) | Igual para todos los casos |
| Tamaño de bloque N | 1024 | Ver `README.md`, sección "Plan de frecuencias" |
| Resolución Δf = fs/N | 15.625 Hz | |
| Latencia de buffer N/fs | 64 ms | |
| Separación mínima ruido–tono útil | 80 Hz | Medida con `src/plan_frecuencias.py` para N = 1024 |
| SNR de entrada | 2 dB en todos los casos | Revisar bien |
| Pico máximo | 0.8 | Ganancia común a señal, ruido y mezcla |
| Fade inicial y final | 20 ms | Evita clics en los bordes del registro |

Bandas de los filtros actuales, como referencia:

| Banda | Rango |
|---|---|
| Paso | 0–1500 Hz |
| Transición | 1500–2300 Hz |
| Rechazo | ≥ 2300 Hz |

## Casos

| Caso | Prueba | Señal útil | Ruido | Semilla |
|---|---|---|---|---|
| caso_1 | Base | Multitono 440/880/1320 Hz | Tonal de 2500 Hz (en bin) | 20261011 |
| caso_2 | P2 | Multitono 440/880/1320 Hz | Banda de 2500–3800 Hz | 20261012 |
| caso_3 | P5 | Multitono 440/880/1320 Hz | Banda de 1000–1800 Hz (superpuesta al tono de 1320) | 20261013 |
| caso_5 | P3 | Audio `audio/3.wav` | Banda ancha de 2000–7500 Hz | 20261015 |
| caso_6 | P4 | Pulso rectangular | Impulsivo | 20261016 |
| caso_7 | P1 | Tono de 440 Hz | Tonal de 2508 Hz (fuera de bin) | 20261017 |

## Señales útiles

| Tipo | Descripción | Parámetros | Casos |
|---|---|---|---|
| Multitono | Suma de 3 sinusoides | 440, 880 y 1320 Hz; amplitudes 1.0, 0.55 y 0.3; fases 0°, 35° y −50° | 1, 2, 3 |
| Tono | Una sinusoide | 440 Hz | 7 |
| Audio | Archivo WAV que se pasa a mono (promediando canales), se convierte a 16 kHz y se recorta a los primeros 6 s | `audio/3.wav`: mono, 48 kHz, 8.9 s, sin saturación, 99.3 % de la energía por debajo de 1500 Hz | 5 |
| Pulso | Rectangular, valor 1 dentro del pulso y 0 fuera; los flancos abruptos muestran la respuesta temporal del filtro | Inicio en t = 3 s, duración 50 ms | 6 |

## Ruidos

| Tipo | Cómo se genera | Parámetros | Casos |
|---|---|---|---|
| Tonal | Sinusoide con fase aleatoria | Frecuencia | 1 (2500 Hz), 7 (2508 Hz) |
| Banda | Ruido blanco gaussiano filtrado con un Butterworth pasa banda de orden 6 (`sosfiltfilt`, solo para generar) | Banda [inferior, superior] | 2, 3, 5 |
| Impulsivo | Impulsos de una muestra, de signo ±1, en posiciones aleatorias | 4 impulsos por segundo (24 en total) | 6 |

En todos los tipos, el ruido se escala para lograr la SNR objetivo y las fases y posiciones aleatorias se reproducen con la semilla del caso.

## Ubicación en bins (N = 1024, Δf = 15.625 Hz)

| Frecuencia | Bin (f/Δf) | ¿Cae en un bin? |
|---|---|---|
| 440 Hz | 28.16 | No |
| 880 Hz | 56.32 | No |
| 1320 Hz | 84.48 | No |
| 2500 Hz (caso_1) | 160.00 | **Sí:** caso favorable, sin fuga espectral |
| 2508 Hz (caso_7) | 160.51 | No: peor caso, casi a mitad entre dos bins |

La interferencia del caso_7 se puso a 8 Hz de la del caso_1 para comparar directamente el caso en bin con el caso fuera de bin. Está a 2068 Hz del tono útil (mucho más que los 80 Hz mínimos) y dentro de la banda de rechazo de ambos filtros.

## Observaciones

- **caso_5:** la banda ancha es ruido filtrado a 2000–7500 Hz, no ruido blanco en todo el espectro, para que quede separada del audio.
- **caso_6:** para lograr 2 dB de SNR, los impulsos alcanzan el pico de 0.8 y el pulso útil queda en ≈ 0.17.
