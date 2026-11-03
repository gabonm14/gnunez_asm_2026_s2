# Nodo 1: adquisición y análisis

Qué pide la especificación (sección 1.1): capturar la señal contaminada con el ADC, eliminar la DC, aplicar ventana, calcular la FFT, estimar las características del ruido y comunicar a los nodos 2 y 3 los datos y parámetros necesarios.

## Cadena de la señal

```
Emisor (ESP32 WROOM-32) → DAC → amplificador → parlante → aire → micrófono → ADC del nodo 1
```

El nodo 1 ya no recibe una señal eléctrica limpia: recibe lo que capta un micrófono en una sala. Eso agrega la respuesta del parlante, del micrófono y de la sala, el ruido ambiente y un retardo acústico (≈ 3 ms por metro).

## Componentes

| Componente | Modelo | Puntos a cuidar |
|---|---|---|
| Micrófono | Módulo electret con MAX4466 | Alimentarlo a **3.3 V**: su salida va de 0 a VCC, y a 5 V puede superar el máximo del ADC. Su salida queda centrada en VCC/2 ≈ 1.65 V. La ganancia se ajusta con el potenciómetro del módulo (≈ 25× a 125×); fijarla y no moverla entre pruebas. Es sensible al ruido de la alimentación: conviene filtrar el 3.3 V del ESP32. |
| Amplificador | PAM8403 (clase D, estéreo) | Va en el emisor, no en el nodo 1. Ganancia fija de ≈ 24 dB (verificar en la hoja de datos). Salida en puente: el parlante va entre L+ y L−, **nunca a GND**. Conmuta a alta frecuencia: separar su alimentación y cables del micrófono. |
| Parlante | 8 Ω, 0.5 W | Limita la potencia: ver la cuenta abajo. Al ser pequeño, probablemente reproduce poco los graves; medir cómo llega el tono de 440 Hz. |

### Límite de nivel para no dañar el parlante

Potencia máxima de 0.5 W sobre 8 Ω:

| Paso | Cuenta | Resultado |
|---|---|---|
| Tensión máxima en el parlante | V_rms = √(P·R) = √(0.5 × 8) | 2.0 V rms |
| Ganancia del PAM8403 | 24 dB | ≈ 15.8 veces |
| Entrada máxima del PAM8403 | 2.0 / 15.8 | ≈ 0.13 V rms (≈ 0.18 V pico en un seno) |
| Salida del DAC del emisor | Pico de 0.8 en la escala ±1, sobre ±1.65 V | ≈ 1.3 V pico |

El DAC entrega unas 7 veces más de lo que el parlante tolera. Hace falta un divisor resistivo o el potenciómetro de volumen del módulo entre el DAC y el PAM8403, y conviene quedarse por debajo del máximo (por ejemplo, la mitad de la potencia). Esto le corresponde a quien haga el emisor, pero afecta el nivel que llega al micrófono.

## Consecuencias del canal acústico

| Efecto | Consecuencia para el nodo 1 | Qué hacer |
|---|---|---|
| Respuesta del parlante y del micrófono | Las amplitudes relativas de los tonos cambian; un parlante pequeño atenúa los graves (440 Hz puede llegar más débil) | Medir la respuesta del canal con tonos o barrido y documentarla |
| SNR en el micrófono | No será los 2 dB del archivo: el canal y la sala la cambian | Medir la SNR real; no asumir la digital |
| Ruido ambiente y eco de la sala | Aparecen componentes que no están en el WAV | Medir el piso de ruido con el emisor en reposo; el diagnóstico debe tolerarlo |
| Sin referencia limpia sincronizada | MSE y SNR no se pueden calcular directamente (lo dice la sección IV-D de `docs/taller_3_asm.pdf`) | Ver "Referencia para las métricas" abajo |
| Retardo acústico y relojes distintos | El bloque capturado no empieza donde empieza la señal emitida | Alinear por correlación cruzada o con una señal de sincronización |
| Nivel | Volumen bajo: poca resolución. Volumen alto: recorte en el ADC o en el amplificador | Ajustar ganancia del amplificador y del micrófono; vigilar recortes |
| Realimentación acústica | Si las salidas de los nodos 2 y 3 suenan cerca del micrófono, vuelven a entrar | Separar parlantes de salida o usar audífonos (sección 5.7) |
| Aliasing | El micrófono y el aire no cortan por encima de 8 kHz | RC anti-aliasing antes del ADC, o micrófono con filtro propio |

## Referencia para las métricas

Para calcular MSE, SNR y energía conservada hace falta la señal limpia tal como llega por el canal. Opciones:

| Opción | Cómo | Ventaja | Desventaja |
|---|---|---|---|
| Grabar la limpia por el mismo canal | El emisor reproduce `limpia`, se captura; luego `contaminada`, se captura; se alinean por correlación | Incluye la respuesta real del canal | Dos capturas; el ruido de la sala cambia entre ellas |
| Pulso de sincronización por cable | El emisor marca con un GPIO el inicio de la tabla; el nodo 1 lo lee | Alineación exacta en tiempo | Un cable extra; la escala del canal se estima aparte |
| Métricas solo espectrales | Atenuación de la interferencia y energía por banda, sin MSE | No necesita referencia | No cubre todas las métricas de la sección 3.5 |

La primera opción, combinada con correlación cruzada, es la más completa. Hay que decidirla con quien haga el nodo 3, porque las métricas se calculan ahí.

## Lo que ya existe en Python

| Parte | Dónde | Qué hace |
|---|---|---|
| Adquisición | `nodo_adquisicion`, `src/pipeline.py` | Simula un ADC de 12 bits entre 0 y 3.3 V, cuenta las muestras recortadas, quita la DC y normaliza |
| Diagnóstico | `diagnosticar`, `src/diagnostico.py` | Promedia FFT (Hann, 50 % de solapamiento) y busca picos, bandas y armónicos de 50/60 Hz. Mide la impulsividad (curtosis) y estima la banda útil, las frecuencias interferentes, la SNR y la confianza. |
| Parámetros para el nodo 3 | `adaptar_config_espectral`, `src/diagnostico.py` | Convierte el diagnóstico en la banda útil del filtro espectral |
| Umbrales del diagnóstico | `metadatos/diagnostico.json` | Umbral de ocupación, ancho de línea, tolerancias, etc. |

Sirve como referencia para validar el firmware: el mismo bloque procesado en el ESP32 y en Python debe dar el mismo resultado.

## Diferencias entre la simulación y el hardware

| Aspecto | En Python | En el ESP32 |
|---|---|---|
| Quitar la DC | Resta el promedio de toda la grabación | Promedio por bloque o pasa altos suave que se va actualizando |
| Diagnóstico | Una sola vez, con el primer segundo | Repetirlo periódicamente para reaccionar a cambios de ruido en la defensa |
| Escala | Divide por una ganancia conocida | La ganancia del canal acústico no se conoce: medirla o trabajar con niveles relativos |
| Canal | No existe: la mezcla llega igual que se generó | Parlante, sala y micrófono cambian amplitudes, agregan ruido y retardo |
| ADC | Ideal y lineal | No lineal cerca de los extremos y ruidoso; conviene calibrarlo |
| Muestreo | Las muestras ya están | Temporizador o ADC continuo con DMA a 16 kHz exactos, nunca `analogRead` en el `loop` |
| Mediana (MAD) | Sin costo | Ordenar 16 000 muestras cuesta tiempo y memoria; simplificar |

## Lo que hay que hacer

### 1. Micrófono y circuito de entrada

- [ ] Alimentar el MAX4466 a 3.3 V y medir su nivel de DC en reposo (≈ 1.65 V); no hace falta divisor
- [ ] Fijar la ganancia del potenciómetro del MAX4466 y documentar la posición
- [ ] RC anti-aliasing entre el micrófono y el ADC (sección 2: demostrar que no hay aliasing)
- [ ] Usar un pin de ADC1 (GPIO32–39 en el WROOM-32; ADC2 deja de funcionar con Wi-Fi)
- [ ] Fijar la distancia parlante–micrófono y documentarla
- [ ] Medir el piso de ruido de la sala con el emisor en reposo
- [ ] Medir la respuesta del canal (parlante + sala + micrófono) a los tonos 440, 880, 1320, 2500 y 2508 Hz
- [ ] Ajustar volumen y ganancia del micrófono sin recortes; documentar los valores

### 2. Captura

- [ ] ADC a 16 kHz exactos (temporizador o modo continuo con DMA)
- [ ] Atenuación de mayor rango (11/12 dB)
- [ ] Doble búfer de N = 1024: uno se llena mientras el otro se procesa (Figura 3 de `docs/taller_3_asm.pdf`)
- [ ] Número de secuencia y marca de tiempo por bloque
- [ ] Detectar recorte (lecturas en 0 o 4095)
- [ ] Detectar desbordamiento de búfer y bloques perdidos (sección 5.3)
- [ ] Verificar la fs real midiendo varios bloques contra el reloj

### 3. FFT

- [ ] Quitar la DC del bloque
- [ ] Ventana Hann periódica: w[n] = ½(1 − cos(2πn/N))
- [ ] FFT de 1024 puntos (por ejemplo, con esp-dsp; documentar su configuración, sección 5.5)
- [ ] Mandar un bloque crudo y su espectro a la computadora y comparar con NumPy: error relativo ≤ 10⁻³ (criterio de la Figura 4 del informe del taller 3)

### 4. Diagnóstico

- [ ] Promediar |X|² de varios bloques (equivalente a `psd_promediada`)
- [ ] Repetir el diagnóstico periódicamente; definir cada cuánto
- [ ] Detectar picos y regiones ocupadas, y estimar las frecuencias interferentes (interpolación parabólica)
- [ ] Estimar la banda útil (`fin_banda_util_hz`) y la confianza
- [ ] Detectar ruido impulsivo con una versión simplificada (sin mediana completa)
- [ ] Decidir si se porta la detección de 50/60 Hz (no hay caso de prueba con red eléctrica)
- [ ] Comparar el diagnóstico del ESP32 con `diagnosticar` de Python sobre los mismos bloques

### 5. Comunicación con los nodos 2 y 3

- [ ] Acordar el medio con quien haga los nodos 2 y 3: UART o SPI
- [ ] Verificar la tasa. Las muestras solas son 16 000 × 2 bytes = 256 kbit/s, más encabezado, así que una UART necesita al menos ~460 800 baudios y es más cómodo 921 600.
- [ ] Definir el paquete por bloque:

| Campo | Contenido |
|---|---|
| Delimitador | Bytes de inicio de bloque |
| Secuencia | Número de bloque, para detectar pérdidas |
| Muestras | N valores int16 con la DC quitada |
| Parámetros | Banda útil, frecuencias interferentes, tipo de ruido, confianza |
| Estado | Recorte o desbordamiento en este bloque |
| CRC | Detección de errores (sección 5.2) |

- [ ] Definir el formato numérico (int16 o float32) y el orden de bytes; justificarlo junto con fs y N (sección 5.4)
- [ ] Probar la recepción en el otro lado con bloques conocidos y verificar el CRC

### 6. Configuración sin recompilar (sección 6)

- [ ] Comandos por serial para cambiar N, umbrales del diagnóstico y periodo de diagnóstico
- [ ] Comando para mostrar el estado: fs medida, bloques perdidos y recortes

### 7. Mediciones para el informe

- [ ] Tiempo de cálculo por bloque (FFT y diagnóstico) en el ESP32 (sección 3.5)
- [ ] Memoria usada (sección 3.5)
- [ ] Latencia de adquisición: 64 ms de llenado por bloque, más procesamiento y envío
- [ ] Capturas del espectro de cada caso de `pruebas/` comparadas con Python

## Criterios de aceptación propuestos

Tomados de la Tabla III y la sección IV-D de `docs/taller_3_asm.pdf`:

| Criterio | Valor |
|---|---|
| Error de la FFT contra NumPy | ≤ 10⁻³ (error relativo) |
| Ubicación de cada pico | A no más de 1 bin (15.625 Hz) de la frecuencia esperada |
| Recorte | Ninguno durante la prueba |
| Bloques perdidos | Ninguno durante la prueba |
| Duración de cada prueba | Al menos 10 s, 3 repeticiones |

## Decisiones pendientes

| Decisión | Con quién |
|---|---|
| Placa del nodo 1: ESP32-S3 o WROOM-32 (cambian los pines del ADC y el driver de muestreo continuo) | Equipo |
| Cómo obtener la referencia para MSE y SNR (captura de la limpia, pulso de sincronización o solo métricas espectrales) | Responsable del nodo 3 |
| Distancia parlante–micrófono y ubicación de las salidas para evitar realimentación | Equipo |
| Medio de comunicación (UART o SPI) y formato del paquete | Responsable de los nodos 2 y 3 |
| Cada cuánto repetir el diagnóstico | Propia |
