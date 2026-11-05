# Emisor (ESP32-WROOM-32)

Fuente de señal del banco de pruebas, integrada en un microcontrolador. Reemplaza al emisor del taller 3 (`avance_taller3_HW/`, para ESP32-S3 con PWM).

```
Emisor (ESP32) → DAC GPIO25 → atenuador → PAM8403 → parlante → aire → micrófono → ADC del nodo 1
```

El ESP32 genera todas las señales en vivo. La única señal que viene de la computadora es la canción de P3 (`audio/3.wav`), guardada en la flash del micro. La computadora no participa durante la emisión.

## Comandos (monitor serial a 115200 baudios, terminar con Enter)

| Comando | Efecto |
|---|---|
| `p <1..5>` | Carga la prueba P1–P5 y emite |
| `s` / `0` | Emite con los parámetros actuales / silencio (DAC en 128, ≈ 1.65 V) |
| `tonos f[:a] ...` | Señal útil: hasta 4 tonos (ej.: `tonos 440:1 880:0.55 1320:0.3`) |
| `audio` | Señal útil: la canción guardada |
| `chirp <f0> <f1> <ms> <periodo_s>` | Señal útil: ráfaga de barrido lineal repetida (ej.: `chirp 600 1400 50 1`) |
| `ruido ninguno\|tono <f>\|blanco\|banda <f1> <f2>\|impulsivo <por_s>` | Ruido que se suma |
| `snr <dB>` | SNR de la mezcla (−40 a 60 dB) |
| `comp mezcla\|limpia\|ruido` | Componente emitida. `limpia` sirve para capturar la referencia por el mismo canal acústico. |
| `vol <0..1>` | Volumen relativo al pico de 0.8 |
| `semilla <n>` | Semilla del ruido aleatorio |
| `estado` / `?` | Parámetros, fs medida, saturaciones y vaciados / ayuda |

Para P6 o para los cambios del profesor durante la defensa se combinan `tonos`, `ruido` y `snr` sin recompilar. Cada cambio reinicia la señal desde su inicio.

## Pruebas P1–P5

Mismas señales que `docs/señales.md`, todas con SNR de 2 dB:

| Comando | Prueba | Señal útil | Ruido |
|---|---|---|---|
| `p 1` | P1 | Tono 440 Hz | Tono 2508 Hz |
| `p 2` | P2 | 440/880/1320 Hz (amplitudes 1, 0.55, 0.3) | Banda 2500–3800 Hz |
| `p 3` | P3 | Canción `audio/3.wav` (6 s en bucle) | Banda 2000–7500 Hz |
| `p 4` | P4 | Chirp de 600 a 1400 Hz, 50 ms, cada 1 s | Impulsivo, 4 por segundo |
| `p 5` | P5 | 440/880/1320 Hz | Banda 1000–1800 Hz (superpuesta al tono de 1320) |

Diferencia con `pruebas/`: el chirp de P4 empieza en t = 0 y se repite sin fin (en `caso_6` hay 5, de t = 1 s a t = 5 s), y el ruido aleatorio sale de otro generador, así que no es idéntico muestra a muestra; sí tiene el mismo espectro y la misma SNR.

## Cómo se genera cada señal

| Señal | Cómo |
|---|---|
| Tonos | Suma de senos de frecuencia y amplitud configurables |
| Canción | `audio.h`: el WAV pasado a mono, a 16 kHz, 6 s con fade de 20 ms, en int8 (96 KB) |
| Chirp | Barrido lineal con envolvente Tukey (25 %), igual que `chirp` y `tukey` de scipy en `src/generacion.py`. Reemplaza al pulso rectangular, que casi no sale del parlante (ver `docs/señales.md`). |
| Ruido tono | Seno |
| Ruido blanco | Gaussiano (Box-Muller sobre un generador xorshift32) |
| Ruido de banda | Gaussiano filtrado por un pasa banda Butterworth de orden 6 aplicado dos veces: el mismo espectro que `butter(6, ...)` con `sosfiltfilt` en `src/generacion.py`. El ESP32 calcula el filtro al configurarlo. |
| Ruido impulsivo | Impulsos de una muestra, signo aleatorio, con la tasa media pedida |

La SNR se fija con la potencia de la señal útil (Σa²/2 para tonos, la medida del audio y la del chirp en un ciclo) y la potencia del ruido, que en el de banda se mide al configurarlo. La salida se normaliza a un pico de 0.8 × volumen sobre la mezcla; limpia y ruido salen con esa misma ganancia. Para el ruido gaussiano se reserva un margen de 4.5σ, que se supera en menos de 1 de cada 100 000 muestras.

## Pines

| Pin | Uso |
|---|---|
| GPIO25 | Salida del DAC (0–3.3 V, centro ≈ 1.65 V) |
| GPIO27 | Pulso de sincronización al inicio de cada ciclo de la señal útil: cada vuelta de la canción, el inicio de cada chirp de P4, o cada segundo con tonos. Va a GPIO35 del nodo 1 |

El ancho del pulso dice qué componente se emite, para que el nodo 1 sepa cuándo puede guardar la referencia limpia (`docs/nodo1_verificacion.md`):

| Componente | Ancho |
|---|---|
| `mezcla` | 1 ms (16 muestras) |
| `limpia` | 2 ms |
| `ruido` | 3 ms |
| Silencio (`0`) | Sin pulsos |

## Conexión al amplificador y al parlante

| Elemento | Detalle |
|---|---|
| Acople | Capacitor en serie (por ejemplo 1–10 µF) entre GPIO25 y la entrada del PAM8403, si el módulo no lo trae: quita el DC de 1.65 V |
| Atenuador | Obligatorio: el DAC entrega ≈ 1.3 V pico y el parlante de 0.5 W solo tolera ≈ 0.18 V pico a la entrada del PAM8403 (ganancia ≈ 24 dB). Divisor de al menos 7:1 o el potenciómetro del módulo. Cuenta en `docs/nodo1.md`. |
| Parlante | Entre L+ y L− del PAM8403, nunca a GND |
| Tierra | Común entre el ESP32 y el PAM8403 |
| Reconstrucción | Conviene un RC después del DAC para suavizar los escalones de 16 kHz; documentar sus valores (sección 5.6 de la especificación) |

## Compilar y cargar

1. Arduino IDE con **esp32 by Espressif Systems 3.3.2**, placa **ESP32 Dev Module** (esquema de particiones por defecto).
2. Abrir `emisor.ino` con `generador.h` y `audio.h` en la misma carpeta, compilar y cargar.
3. Monitor serial a 115200 baudios, fin de línea "Nueva línea".

Con `arduino-cli`:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 emisor
arduino-cli upload --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 emisor
```

Si se cambia la canción, regenerar `audio.h` (desde la carpeta del proyecto): `python emisor/generar_audio.py`.

## Archivos

| Archivo | Contenido |
|---|---|
| `emisor.ino` | Temporizador, interrupción, DAC, búfer circular, tarea productora y comandos serial |
| `generador.h` | Generación de las señales y pruebas P1–P5. Sin dependencias de Arduino. |
| `audio.h` | Canción de P3; lo genera `generar_audio.py` |
| `prueba/` | Verificación en la computadora. El Arduino IDE no compila esta subcarpeta. |

## Diseño

| Decisión | Motivo |
|---|---|
| Temporizador de 2 MHz con alarma cada 125 cuentas | 16 000 muestras/s exactas en cuentas del reloj |
| Interrupción mínima, en IRAM | Solo saca una muestra del búfer al DAC y maneja el pulso de sincronización. Usa `IRAM_ATTR` porque `ARDUINO_ISR_ATTR` no ubica la función en IRAM en el núcleo 3.x. |
| Tarea productora en el núcleo 0 | Calcula bloques de 256 muestras y llena un búfer circular de 4096 (256 ms) |
| Uso de recursos | 423 KB de flash y 26 KB de RAM, según la compilación |

`estado` informa las muestras saturadas y los vaciados del búfer (la tarea no alcanzó a llenarlo). Ambos deben quedar en 0.

## Verificación en la computadora

```bash
python emisor/prueba/verificar_generador.py
```

Compila `generador.h` con g++ (el mismo código que corre en el ESP32) y comprueba, 29/29:

| Verificación | Resultado |
|---|---|
| SNR de P1–P5 a 2 dB | Entre 1.59 dB (P4, pocos impulsos) y 2.08 dB |
| Mezcla = limpia + ruido, con la misma ganancia | Exacto en las 5 pruebas |
| Sin saturar el DAC en 30 s | Pico máximo 0.82 |
| Frecuencias de P1, tasa de impulsos de P4 | Correctos |
| Chirp igual a la limpia de `caso_6` | Error 105 dB por debajo |
| Ruido de banda igual al de `generacion.py` | Desvío de la PSD menor a 1 dB en las 3 bandas |
| Canción igual a la limpia de `caso_5` | Error 34 dB por debajo (cuantización int8) |
| `snr`, `tonos`, `ruido`, `vol`, `semilla` | Correctos |

No incluye el DAC, el temporizador ni el canal acústico.

## Verificación pendiente en la placa

1. Con `0`, medir ≈ 1.65 V en GPIO25.
2. `estado` varias veces: la fs medida debe ser ≈ 16 000 Hz y los vaciados 0.
3. `p 1` y `comp limpia`: tono de 440 Hz; comprobar la frecuencia con osciloscopio o con la FFT del nodo 1.
4. Escuchar cada prueba con volumen bajo antes de subirlo.
5. Medir el nivel en la entrada del PAM8403 con el atenuador, por debajo de ≈ 0.18 V pico.
