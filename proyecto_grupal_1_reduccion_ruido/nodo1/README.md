# Nodo 1 — adquisición y análisis (ESP32 DevKit de 38 pines)

```
Emisor (ESP32) → DAC → PAM8403 → parlante → aire → micrófono MAX4466 → RC → ADC del nodo 1 → UART2 → nodos 2 y 3
```

El nodo 1 capta con un micrófono la señal contaminada que reproduce el emisor y la muestrea a 16 kHz. La procesa por bloques: quita la DC, aplica una ventana Hann y calcula la FFT con esp-dsp. Con eso diagnostica el ruido cada cierto periodo y envía a los nodos 2 y 3 una trama por bloque con las muestras, el estado y los parámetros del diagnóstico. El diagnóstico es una traducción de `diagnosticar()` de `src/diagnostico.py`, y se valida contra esa función con **las mismas muestras**, incluso en capturas reales del micrófono.

## Archivos

| Archivo | Contenido |
|---|---|
| `nodo1_esp32/nodo1_esp32.ino` | Todo el firmware, por secciones: tipos, FFT, procesamiento, diagnóstico, trama, consola y captura (ADC, doble búfer, seguidor de DC, UART2) |
| `host/Makefile` | Compila el mismo `.ino` en la PC (`make -C host`). Sin `ARDUINO`, usa una FFT de referencia y la consola por stdin/stdout |
| `validacion/conexion.py` | Habla con la placa (USB) o con el ejecutable de PC usando el mismo protocolo |
| `validacion/validar_fft.py` | FFT del nodo frente a NumPy y a la DFT directa. Con `--adc`, sobre un bloque real del micrófono |
| `validacion/comparar_diagnostico.py` | Diagnóstico del nodo frente a `diagnosticar()` con los casos de `pruebas/` y señales sintéticas |
| `validacion/trama.py` | Formato de la trama y un decodificador independiente del firmware |
| `validacion/validar_tramas.py` | Recepción con bloques conocidos, fallas inyectadas, parámetros dentro de la trama y UART real |
| `validacion/capturar.py` | Guarda en `.npz` las tramas reales de GPIO17. Con `--simular CASO`, pasa un caso por el firmware sin micrófono |
| `validacion/analizar_captura.py` | Revisa una captura contra los criterios y compara el diagnóstico con Python sobre los mismos bloques. Mide tonos, canal, piso de ruido y repeticiones |
| `validacion/circuito_entrada.py` | Calcula el anti-aliasing (RC más el ancho de banda del MAX4466) y el rango del ADC |
| `capturas/`, `resultados/` | Capturas (`sim_*`: simuladas, sin canal acústico) y salidas de los scripts |

## Conexiones

| Señal | Pin | Nota |
|---|---|---|
| Micrófono → RC → ADC | **GPIO34** (ADC1_CH6) | Solo entrada. No usar el ADC2, porque deja de funcionar con WiFi |
| MAX4466 VCC | **3.3 V** del ESP32, filtrado (por ejemplo, 100 Ω en serie y 10 µF a GND) | A 5 V su salida puede pasar el máximo del ADC. El módulo es sensible al ruido de la alimentación |
| Tramas TX → nodos 2 y 3 | **GPIO17** (UART2) | 921600 baudios, 8N1, 3.3 V |
| UART2 RX | GPIO16 | Prueba de lazo (puente GPIO17 → GPIO16) |
| Consola | USB | 921600 baudios, fin de línea **Nueva línea** |
| GND | común | Con el emisor y los nodos 2 y 3. Separar los cables del PAM8403 de los del micrófono |

## Circuito de entrada y anti-aliasing

```
MAX4466 OUT ── 1 kΩ ──┬── 1 kΩ ──┬──► GPIO34
(DC ≈ 1.65 V)        10 nF      10 nF
                      │          │
                     GND        GND
```

Los valores salen de `validacion/circuito_entrada.py`; ver `resultados/circuito_entrada.json` y `.png`.

- **No hace falta divisor ni acople.** El módulo ya centra la salida en VCC/2 ≈ 1.65 V y el RC deja pasar la DC. El firmware sigue esa DC con un pasa altos suave.
- **Rango del ADC.** Con 12 dB, el rango lineal recomendado es de 0.15 a 2.45 V. Con la DC en 1.65 V, el límite lo pone el lado alto, así que el **pico de la señal no debe pasar de 0.8 V**. El comando `adc` muestra `min_mv` y `max_mv` del último intervalo; con eso se ajusta la ganancia.
- **RC de dos etapas.** Corte de −3 dB en 5.9 kHz. Atenúa −0.2 dB en 1320 Hz, −0.7 dB en 2500/2508 Hz, −4.2 dB en 7500 Hz y −7.2 dB en 12 kHz (que se refleja en 4 kHz).
- **El MAX4466 también filtra.** Su producto ganancia-ancho de banda es de ~200 kHz, así que con ganancia G se comporta como un polo en 200 kHz / G. Con el RC queda:

| Ganancia del MAX4466 | 1320 Hz | 2500 Hz | 7500 Hz | 12 kHz (alias en 4 kHz) |
|---|---|---|---|---|
| 25× (polo en 8 kHz) | −0.3 dB | −1.1 dB | −6.9 dB | −12.4 dB |
| 50× (polo en 4 kHz) | −0.7 dB | −2.1 dB | −10.7 dB | −17.2 dB |
| 125× (polo en 1.6 kHz) | −2.5 dB | −6.1 dB | −17.8 dB | −24.8 dB |

  **Recomendación:** ganancia entre 25× y 50×, y ajustar el nivel con el volumen del emisor y la distancia. Con 125× ya se atenúan la interferencia de 2500 Hz y el ruido de banda alto, y eso cambia lo que diagnostica el nodo.
- **Demostrar que no hay aliasing** (sección 2). La atenuación calculada no basta, hay que medirla:
  1. Con el emisor apagado, reproducir cerca del micrófono un tono de 12 kHz desde un teléfono o una PC (el emisor no puede generar frecuencias sobre 8 kHz). Capturar.
  2. Repetir con un tono de 4 kHz al mismo volumen.
  3. Comparar ambos niveles con `analizar_captura.py --tonos 4000`. La diferencia es la atenuación real del alias. Si queda corta, bajar el corte del RC (por ejemplo, 1.5 kΩ / 15 nF) o usar un Sallen-Key.

## Captura

- **16 kHz exactos.** Un temporizador de 2 MHz dispara una alarma cada 125 cuentas (62.5 µs), igual que el emisor. Su interrupción despierta a `tarea_adc`, que tiene prioridad máxima en el núcleo 0 y lee el ADC1 con `adc_oneshot_read` y `ADC_ATTEN_DB_12`.
  - No se usa `analogRead` en `loop()`.
  - No se usa el modo continuo (DMA) porque en el WROOM-32 no baja de 20 kHz.
  - No se lee el ADC dentro de la interrupción porque el driver no lo permite.
- **Doble búfer de 1024 muestras.** Mientras la tarea llena un búfer, `loop()` (núcleo 1) procesa el otro.
- **Por bloque:** número de secuencia y marca de tiempo (`esp_timer`). Además se detectan:
  - *recorte:* lecturas en 0 o 4095;
  - *atraso:* la tarea despertó tarde; se repite la lectura y se cuenta;
  - *desbordamiento:* `loop()` no liberó el otro búfer; el bloque se pierde y la secuencia salta;
  - *UART saturada:* la trama se descarta.
- **Quitar la DC.** Un pasa altos de primer orden, dc ← dc + (x − dc)/8192 (constante de 0.5 s, corte en 0.3 Hz), se resta muestra a muestra.
  - Es mejor que restar la media de cada bloque, porque esa resta deja escalones entre bloques que en los nodos 2 y 3 sonarían como clics.
  - Arranca en la media del primer bloque para no tener un transitorio largo.
- **fs real.**
  - En el firmware: fs = muestras (según la secuencia) / tiempo de `esp_timer`. Se marca si se aleja más de 0.5 %.
  - En la PC: `analizar_captura.py` la mide con las marcas de tiempo y con el reloj de la PC, que es independiente del cristal del ESP32.
- **Latencia por bloque** (comando `adc`): 64 ms de llenado + el peor tiempo de procesamiento + 23 ms de envío de la trama.

## Trama hacia los nodos 2 y 3

Todo va en little-endian. El CRC-32 es igual a `zlib.crc32` y cubre todo menos el delimitador. El detalle está en `validacion/trama.py`.

| Bytes | Campo |
|---|---|
| 0–3 | Delimitador `A5 5A`, versión (2) y longitud de cabecera (84) |
| 4–9 | Secuencia y número de muestras (1024) |
| 10–23 | Estado (recorte, atraso, pérdida, diagnóstico nuevo, fs fuera de tolerancia, prueba), recortadas, atrasadas, perdidos acumulados y fs medida |
| 24–69 | **Parámetros del diagnóstico**: número, tipos, confianza y banderas, fin de la banda útil, hasta 4 frecuencias interferentes, banda de ruido, frecuencia de red, SNR estimada y N de la FFT |
| 70–71 | DC restada, en código del ADC |
| 72–75 | Marca de tiempo del bloque (µs) |
| 76–83 | Índice de la muestra donde terminó el último diagnóstico y cuántas muestras cubrió, para repetirlo en Python sobre las mismas muestras |
| 84… | 1024 muestras **int16 con la DC quitada**, en unidades del ADC (1 LSB ≈ 0.76 mV) |
| final | CRC-32 |

**Justificación conjunta (sección 5.4):**
- **fs = 16 kHz.** Nyquist queda en 8 kHz, por encima de los tonos útiles (≤ 1320 Hz), de la interferencia (2508 Hz) y del ruido de los casos (≤ 7.5 kHz).
- **N = 1024.** Son 64 ms por bloque y 15.6 Hz de resolución; es potencia de dos.
- **Formato int16.** Los 12 bits del ADC caben sin pérdida, ya con signo y sin DC, listos para filtrar. float32 duplicaría la tasa sin agregar información.
- **Tasa.** 2136 B cada 64 ms son 334 kbaud. A 921600 baudios se usa el 36 % del canal y la trama tarda 23 ms en salir.

## Diagnóstico

- Ventana Hann periódica, w[n] = ½(1 − cos(2πn/N)), igual a `get_window('hann', N)`. No se usa `dsps_wind_hann_f32` porque es la simétrica.
- FFT con `dsps_fft2r_fc32` (ae32) y `dsps_bit_rev_fc32`. La tabla de factores de giro se inicializa una vez para 2048. Buffers alineados a 16 B en RAM interna y sin normalizar, como NumPy.
- PSD media de |X|² con 50 % de solapamiento. Encuentra picos y regiones ocupadas, estima las frecuencias interferentes con interpolación parabólica y calcula la banda útil y la confianza.
- **Periodo de 1 s** (ajustable con `set periodo`). Junta 30 marcos promediados, lo que estabiliza la PSD frente al ruido de la sala, y deja reaccionar a un cambio de ruido en la defensa en 1 a 2 s.
- **Impulsivo simplificado.** Curtosis de la primera diferencia, con la mediana y la MAD por trozos de 1024 muestras en vez de ordenar las 16 000.
- **50/60 Hz.** Se dejó portado: no cuesta casi nada y el micrófono puede captar zumbido de la red por la alimentación o el ambiente. No hay caso de prueba que lo use.

## Uso

1. Arduino IDE con **esp32 by Espressif Systems 3.3.x** (compilado con 3.3.11) y placa **ESP32 Dev Module**. El core ya incluye esp-dsp y `esp_adc`; no hay que instalar bibliotecas. Ocupa el 25 % de la flash y el 19 % de la RAM.
2. Cargar `nodo1_esp32/nodo1_esp32.ino`. El nodo arranca capturando del micrófono y aparece un `DIAG {...}` por segundo.

| Comando | Efecto |
|---|---|
| `adc` | fs medida, bloques, perdidos, atrasadas, recortadas, DC, mín./máx. en código y mV, tiempo de proceso, latencia y uso de la UART |
| `cfg`, `set <clave> <valor>` | Parámetros sin recompilar (alias `n`, `periodo`, `umbral`, `curtosis`, `kmad`). La fs queda fija en 16000 |
| `diag`, `reiniciar`, `tiempos`, `mem` | Diagnosticar ya, descartar lo acumulado, tiempos por etapa y memoria |
| `fuente adc\|sint\|patron\|nada` | Micrófono, señal sintética (`interferencia <hz>` la cambia), bloques conocidos o nada |
| `tramas on\|off`, `rx` | Envío por UART2 y tramas recibidas en GPIO16 |
| `fft_prueba [adc]`, `muestras <L> [periodico] [tramas]`, `prueba_trama`, `tramas_conocidas <k>` | Usados por los scripts |

## Validación y mediciones

Se necesitan NumPy, SciPy y Matplotlib, y además `pyserial` para la placa. Los comandos van desde `proyecto_grupal_1_reduccion_ruido/`. Para `--uart` se usa un adaptador USB-UART: GPIO17 a su RX, con GND común.

```bash
# sin micrófono (también corren en la PC, sin --puerto)
python nodo1/validacion/validar_fft.py --puerto COM3 --adc
python nodo1/validacion/comparar_diagnostico.py --puerto COM3
python nodo1/validacion/validar_tramas.py --puerto COM3 --uart COM4 --segundos 60

# con el micrófono: 3 repeticiones de >= 10 s por caso
python nodo1/validacion/capturar.py --uart COM4 --puerto COM3 --segundos 12 --salida nodo1/capturas/caso_1_r1.npz --nota "caso_1, 50 cm, MAX4466 a 25x, volumen 3"
python nodo1/validacion/analizar_captura.py nodo1/capturas/caso_1_r*.npz --caso caso_1 --tonos 440 880 1320 2500
```

| Medición pedida | Cómo |
|---|---|
| Piso de ruido de la sala | Capturar con el emisor en reposo (`--nota piso`) y analizar; reporta RMS en dBFS y potencia por bandas |
| Respuesta del canal a 440, 880, 1320, 2500 y 2508 Hz | Capturar `caso_1` y `caso_7`, y analizar con `--caso` y `--tonos`. Da el nivel de cada tono y su diferencia con el espectro digital (`canal_relativo_db`, sin la ganancia media) |
| Nivel sin recortes | `adc` durante la prueba: `max_mv` < 2450, `min_mv` > 150 y `muestras_recortadas` en 0 |
| SNR real en el micrófono | Capturar la señal `limpia` y luego la `contaminada`, y analizar con `--limpia`: alinea por correlación y estima el retardo, la ganancia y la SNR |
| FFT de un bloque real frente a NumPy | `validar_fft.py --adc` |
| Diagnóstico frente a Python sobre los mismos bloques | `analizar_captura.py`: cada diagnóstico de las tramas se repite en Python con las muestras que cubrió |
| Tiempo, memoria y latencia | `tiempos`, `mem` y `adc` en la placa |

Criterios de aceptación (Tabla III y sección IV-D de `docs/taller_3_asm.pdf`), los mismos que revisa `analizar_captura.py`:

| Criterio | Valor |
|---|---|
| Error de la FFT frente a NumPy | ≤ 10⁻³ |
| Ubicación de cada pico | ≤ 1 bin (15.625 Hz) |
| Recortes y bloques perdidos | ninguno |
| Duración y repeticiones | ≥ 10 s, 3 repeticiones |
| Diagnóstico frente a Python, mismas muestras | mismos tipos y confianza; líneas a ≤ 1 Hz; bordes a ≤ 1 bin; SNR a ≤ 0.5 dB |

Resultados en la PC (FFT de referencia, no esp-dsp, y sin canal acústico):

| Prueba | Resultado |
|---|---|
| FFT, cuatro tamaños de N | error ≤ 6.6·10⁻⁷ |
| Diagnóstico frente a Python | 21/21 |
| Tramas (cuatro pruebas) | cumplen |
| Capturas simuladas de `caso_1`, `caso_2` y `caso_7` | 15/15 diagnósticos iguales a Python sobre las mismas muestras; picos a menos de 0.3 Hz |

**Falta todo lo físico:**
- compilar y cargar;
- montar el micrófono y el RC;
- fijar la ganancia y la distancia;
- medir el piso de ruido, la respuesta del canal y el aliasing;
- hacer las capturas de cada caso con 3 repeticiones;
- correr los scripts con `--puerto`.

Con `adc`, revisar `lectura_max_us`: debe quedar holgado bajo 62.5 µs. Si aparecen muestras atrasadas sin carga, habría que leer el ADC por registros.

## Decisiones pendientes

| Decisión | Con quién | Estado en este código |
|---|---|---|
| Placa del nodo 1 | Equipo | Hecho para WROOM-32 (38 pines). En una S3 cambian el pin del ADC y conviene usar el modo continuo |
| Referencia para MSE y SNR | Responsable del nodo 3 | `analizar_captura.py --limpia` implementa la opción "grabar la limpia por el mismo canal y alinear por correlación" |
| Distancia parlante–micrófono y ubicación de las salidas | Equipo | Se registra en `--nota` de cada captura |
| UART o SPI y formato del paquete | Responsable de los nodos 2 y 3 | Propuesta: UART2 a 921600 con la trama de arriba; `receptor_byte` (C++) y `trama.py` (Python) sirven para el lado receptor |
| Periodo del diagnóstico | Propia | 1 s (ver Diagnóstico) |

Límite de nivel del parlante (lo ajusta el emisor): 0.5 W en 8 Ω son 2 V rms en el parlante, o sea ≈ 0.13 V rms a la entrada del PAM8403 (+24 dB). El DAC entrega unas 7 veces más, así que hace falta un divisor o el potenciómetro del módulo.

Preparado con asistencia de IA (Claude) para la implementación y la validación numérica. Hay que revisar cada línea antes de la defensa y registrar esta ayuda en el documento de herramientas.
