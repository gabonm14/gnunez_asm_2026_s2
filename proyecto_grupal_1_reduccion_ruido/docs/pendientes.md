# Pendientes del proyecto

Revisión del repositorio contra `ASM_Proyecto_Grupal1_v7.pdf`, rama `development` (commit `7141049`), al 1 de noviembre de 2026. Entrega y defensa: 6 de noviembre de 2026.

## Ya cumplido

| Requisito | Sección | Dónde |
|---|---|---|
| Señales y ruidos mínimos (P1–P5) | 2.1, 2.2 | `docs/señales.md`, `src/generacion.py` |
| DFT por definición contra FFT | 3.2.2 | `src/analisis.py` |
| FIR e IIR candidatos (Butterworth y Chebyshev en secciones de segundo orden) | 3.2.3 | `src/filtros_temporales.py`, `src/filtros_iir.py` |
| Polos, ceros, ROC, respuesta en frecuencia y estabilidad de FIR e IIR | 3.2.4, 3.3 | `resultados/figuras/fir_*.png`, `iir_*.png` |
| Cuantización de coeficientes de FIR e IIR | 3.3.6 | `resultados/fir_cuantizacion.csv`, `iir_cuantizacion.csv` |
| Método espectral por bloques, con versión adaptativa según el diagnóstico | 3.4 | `src/filtrado_espectral.py`, `src/diagnostico.py` |
| Diagnóstico del nodo 1: tipo de ruido, frecuencias y banda | 1.1 | `src/diagnostico.py` |
| Sistema completo simulado: emisor → ADC de 12 bits → nodo 1 → nodos 2 y 3 → métricas | 3.2.6 | `src/pipeline.py`, `resultados/pipeline_resumen.md` (6 casos) |
| Costo, memoria y latencia estimados | 3.2.7 | `resultados/iir_vs_fir.csv`, `pipeline_etapas.csv` |
| Métricas obligatorias y criterios de aceptación definidos antes de las pruebas | 3.5 | `src/metricas.py`, `metadatos/comparacion.json` |
| Plan de frecuencias: fs, N, separación mínima y latencia | 2, 5.4 | `docs/frecuencias.md` |
| Emisor: firmware escrito y tablas verificadas digitalmente | — | `avance_taller3_HW/` |
| Pruebas automáticas | — | `tests/`: 61 pruebas, todas pasan |

## Software

| Pendiente | Detalle |
|---|---|
| `src/ejecutar_todo.py` no corre | Importa `actualizar_informe.py`, que no existe. Tampoco incluye `filtros_iir`, `diagnostico`, `emisor`, `pipeline` ni `plan_frecuencias`. La especificación pide reproducir automáticamente figuras y tablas (3.2). |
| Resultados duplicados y desactualizados | `resultados/metricas.csv`, `comparacion/`, `temporal/` y `espectral/` (de `comparacion.py`) solo tienen los casos 1–3. `resultados/pipeline_*` sí tiene los 6 casos. Definir cuál es el resultado oficial y regenerar o retirar el otro. |
| `src/pipeline.py` falla en un clon limpio | No crea `resultados/figuras` antes de guardar la figura; los demás módulos sí |
| 3 repeticiones por prueba P1–P5 con promedio y variabilidad | Sección 4. Hoy hay 1 corrida por caso; se puede hacer con varias semillas por caso |
| Formato numérico y tasa de comunicación | Sección 5.4: justificarlos junto con fs y N. `docs/frecuencias.md` solo tiene fs y N. |

## Hardware: nodos (65 % de la nota)

No hay firmware de ningún nodo en el repositorio; solo existe el emisor.

| Requisito | Sección |
|---|---|
| Nodo 1: ADC a 16 kHz, quitar DC, ventana Hann, FFT de 1024, estimar ruido y enviar parámetros | 1.1 |
| Nodo 2: FIR o IIR en el MCU, salida por DAC/PWM con filtro analógico documentado | 1.1, 3.3, 5.6 |
| Nodo 3: FFT/IFFT en el MCU, métricas y pantalla o interfaz con método activo, energía, MSE y SNR antes y después | 1.1 |
| Comunicación cableada con delimitación de bloques y CRC | 5.2 |
| Avisar pérdidas de bloques y desbordamientos de búfer | 5.3 |
| Filtro anti-aliasing antes del ADC | 2 |
| Validar la FFT del MCU contra la referencia en Python | 5.5 |
| Parámetros ajustables sin recompilar | 6 |
| Comparar la respuesta del filtro calculada con la medida | 3.3.5 |
| Latencia, memoria y carga medidas en el MCU | 3.5 |
| Prueba auditiva en P1–P6 | 4 |

El diseño del receptor (Figuras 2–4 de `docs/taller_3_asm.pdf`) sirve como guía para el nodo 1.

## Hardware: emisor (`emisor/`)

Cadena definida: emisor (ESP32-WROOM-32) → DAC → amplificador → parlante → aire → micrófono → ADC del nodo 1. El firmware nuevo está en `emisor/` y reemplaza a `avance_taller3_HW/` (ESP32-S3 con PWM).

| Hecho | Detalle |
|---|---|
| Firmware para WROOM-32 | DAC de GPIO25 a 16 kHz exactos; compila con Arduino-ESP32 3.3.2 |
| Señales generadas en el micro | P1–P5 con `p 1`…`p 5`; todo se calcula en vivo salvo la canción de P3, guardada en flash |
| Parámetros sin recompilar (P6 y defensa) | Tonos, audio o chirp; ruido tono, blanco, banda o impulsivo; SNR, volumen, semilla |
| Referencia limpia | `comp limpia` con la misma ganancia que en la mezcla |
| Pulso de sincronización | GPIO27 |
| Verificación en computadora | `emisor/prueba/verificar_generador.py`: 29/29 |

| Pendiente | Detalle |
|---|---|
| Cargar y medir en la placa | Pasos de "Verificación pendiente en la placa" en `emisor/README.md` |
| Atenuador hacia el PAM8403 | El DAC entrega ≈ 7 veces la entrada máxima que tolera el parlante de 0.5 W con los 24 dB del PAM8403: divisor o potenciómetro (cuenta en `docs/nodo1.md`). Parlante entre L+ y L−, nunca a GND (sección 5.7). |
| Filtro de reconstrucción del DAC | Elegir valores, montarlo y documentarlo (sección 5.6) |

## Documentación (35 % de la nota)

| Pendiente | Sección | Detalle |
|---|---|---|
| Paper en LaTeX, máximo 4 páginas, formato IEEE/ACM | 8 | No existe. Incluye abstract en inglés, revisión teórica de 1 página con citas (3.1), resultados, conclusiones y recomendaciones. |
| Documento de herramientas de ingeniería, máximo 2 páginas | 8 | No existe. La sección "Herramientas utilizadas" de `docs/taller_3_asm.pdf` sirve de base. |
| README desactualizado | — | Título "Tarea 1", fecha del 14 de octubre, 2 integrantes (el informe del taller lista 4); no menciona IIR, diagnóstico, emisor ni pipeline |
| Documentos de los módulos nuevos | — | `docs/` no tiene explicación de `filtros_iir`, `diagnostico`, `emisor` ni `pipeline`. Útil para la defensa, donde el profesor puede pedir justificar cualquier línea (6). |
| Declaración de uso de IA | 8 | El README solo menciona ChatGPT |
| Origen y permiso de `audio/3.wav` | 5.8 | No documentado |

## Repositorio

| Pendiente | Detalle |
|---|---|
| Rama `master` | La especificación pide `master` y `development` (7.4); el repo usa `main` |
| `main` desactualizada | `main` sigue en `5474ac6` (Tarea 1); todo el trabajo del proyecto está solo en `development` |
| Tag del proyecto | Existen `tarea1_prototipo` y `1.0.0` (proyecto individual); falta el tag del proyecto grupal al fusionar en `master`/`main` |
| Archivo suelto | `taller_3_asm.pdf` sin seguimiento en la raíz del proyecto, duplicado de `docs/taller_3_asm.pdf` |

## Prioridad sugerida

1. Nodos 1, 2 y 3 en hardware con comunicación por bloques y CRC.
2. Cargar el emisor en la placa, montar el atenuador y el filtro de reconstrucción, y medir.
3. Paper y documento de herramientas, en paralelo.
4. Arreglar `ejecutar_todo.py`, definir el resultado oficial y agregar las 3 repeticiones.
5. Fusionar en `master`/`main` y crear el tag.
