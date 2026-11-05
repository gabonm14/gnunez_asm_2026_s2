# Cómo leer lo que recibe el nodo 2/3 desde el nodo 1

`prueba_uart_oled.ino` corre en el ESP32-S3 de los nodos 2 y 3. Recibe las tramas que manda el nodo 1, las valida y cada 0.5 s imprime qué llegó. Sirve para comprobar el enlace antes de filtrar, y para saber qué datos va a tener el filtro en cada prueba.

## Conexión y monitor

| Qué | Valor |
|---|---|
| Cable de datos | GPIO17 del nodo 1 (TX) → GPIO16 del S3 (RX) |
| Tierra | GND del nodo 1 con GND del S3 |
| Enlace | 921 600 baudios, 8N1 (fijo en los dos lados) |
| Monitor serie del S3 | **115 200** baudios (solo la consola; no tiene que ver con el enlace) |

Cargar el código reinicia el S3 y pone los contadores en cero. **No abrir ni cerrar el monitor del nodo 1 durante una prueba**: eso lo reinicia y borra la referencia limpia.

## Qué imprime

Cada 0.5 s salen dos líneas:

```
bytes 32576 | tramas validas 8 (total 1466) | CRC malo 1 | perdidas 2 | reinicios del nodo 1 1
   seq 1515 | estado 0x48 (con referencia) | diagnostico #97 tipos [tonal] lineas [2508.0, 3387.8] Hz | banda nan-nan Hz | muestras: -327 -217 -5 152 104 -51 -211 -179
```

### Primera línea: el enlace

| Campo | Qué es | Correcto | Problema si… |
|---|---|---|---|
| `bytes` | Bytes recibidos en los últimos 0.5 s | **16 000–17 200** sin referencia (tramas de 2144 B); **32 000–33 600** con referencia (tramas de 4192 B) | `0`: no llega nada (cable, GND, nodo 1 apagado o con `tramas off`) |
| `tramas validas` | Tramas completas con CRC correcto en los últimos 0.5 s | **7 u 8** (una cada 64 ms) | `0` con bytes > 0: llega basura (baud rate distinto o pin equivocado) |
| `total` | Tramas válidas desde que arrancó el S3 | Sube 7–8 por línea | — |
| `CRC malo` | Tramas con algún byte dañado, **acumulado** | **No sube** durante la prueba. Puede quedar 1–2 de cuando se conectó o se reinició algo. | Sube seguido: GND flojo, cable largo, o el S3 no alcanza a leer |
| `perdidas` | Tramas que no llegaron (saltos en la secuencia), **acumulado** | **No sube** durante la prueba | Sube: se desborda el búfer del S3 (leer por bloques, búfer de 16 KB) |
| `reinicios del nodo 1` | Veces que la secuencia volvió a empezar | 0, o lo que se haya reiniciado a propósito | Sube solo: el nodo 1 se reinicia (alimentación, o alguien abrió su monitor) |

Los contadores acumulados importan por si **cambian**, no por su valor: anotar el número al empezar la prueba y comprobar que no se mueve.

### Segunda línea: la última trama

| Campo | Qué es |
|---|---|
| `seq` | Número del bloque. Sube 7–8 por línea, sin saltos |
| `estado` | Avisos del nodo 1 (tabla siguiente) |
| `diagnostico #` | Número del diagnóstico; cambia una vez por segundo (16 tramas seguidas llevan el mismo) |
| `tipos` | Tipo de ruido que diagnosticó el nodo 1: `tonal`, `banda`, `impulsivo`, `red_electrica`; vacío si no encontró ruido |
| `lineas` | Hasta 4 frecuencias de ruido tonal, en Hz |
| `banda` | Banda de ruido [inicio–fin] en Hz; `nan-nan` si no hay |
| `muestras` | Las primeras 8 de las 1024 muestras del bloque (int16, sin la DC, en códigos del ADC) |

### Bits del estado

| Bit | Valor | Significa | ¿Normal? |
|---|---|---|---|
| — | `0x00` | Nada que avisar | ✔ |
| 3 | `0x08` | Diagnóstico nuevo en esta trama (una vez por segundo) | ✔ |
| 6 | `0x40` | La trama trae la **referencia limpia** | ✔ con la referencia guardada |
| 3 + 6 | `0x48` | Las dos anteriores | ✔ |
| 0 | `0x01` | Alguna muestra saturó el ADC | ✘ Bajar la ganancia del micrófono o el volumen |
| 1 | `0x02` | El nodo 1 leyó tarde alguna muestra | ✘ si se repite |
| 2 | `0x04` | El nodo 1 perdió bloques (desborde) | ✘ |
| 4 | `0x10` | La frecuencia de muestreo se salió de 16 000 Hz ± 0.5 % | ✘ |
| 5 | `0x20` | Señal de prueba del nodo 1 (`fuente sint` o `patron`), no del micrófono | Solo si se pidió |

Si aparecen otros valores, se suman: `0x41` = referencia + saturación.

## Qué esperar en cada prueba

Medido con el montaje final: micrófono a 10 cm, PAM8403 al máximo, emisor en `vol 1`, y el diagnóstico con `umbral_ocupacion_db` 30, `ancho_linea_hz` 125 y `separacion_impulsos_ms` 30. "Típicas" es el valor que no superan el 95 % de las muestras, en códigos del ADC. Si se cambia la distancia, el volumen o la ganancia del micrófono, las muestras cambian de tamaño, pero el diagnóstico debería ser el mismo.

### Emisor en `comp mezcla` (lo que se filtra)

| Prueba | Ruido insertado | `tipos` esperado | `lineas` / `banda` esperadas | Aceptable también | Muestras: típicas / máximo |
|---|---|---|---|---|---|
| **P1** | Tono de 2508 Hz | `[tonal]` | `lineas` con **2508.0** (± 0.1) | Además 3387.8 Hz (intermodulación del parlante) y a veces 5492 Hz (reflejo respecto a 8 kHz) | ±320 / 370; oscilan cada ~6 muestras (el tono de 2508 Hz domina) |
| **P2** | Banda de 2500–3800 Hz | `[banda]` | `banda` ≈ **2375–4900** Hz | `[tonal, banda]` con alguna línea suelta en 5000–5500 Hz | ±280 / 670; aspecto de ruido |
| **P3** | Banda de 2000–7500 Hz + canción | Variable: casi siempre `[]`, a veces `[banda]` | Bandas que cambian de periodo a periodo | Cualquiera: la canción ocupa casi todo el espectro y el diagnóstico no la separa del ruido (igual en la simulación) | ±110 / 300 |
| **P4** | Impulsivo, 4 por segundo | `[impulsivo]` | Ninguna | `[impulsivo, red_electrica]` con líneas de 50–600 Hz en algún periodo | ±20 / 310: casi siempre pequeñas, con picos sueltos (los clics y el chirp) |
| **P5** | Banda de 1000–1800 Hz | `[banda]` | `banda` ≈ **844–1938** Hz | `[tonal, banda]` o `[]` en algún periodo | ±180 / 400 |

### Emisor en `comp limpia` (sin ruido)

| Prueba | `tipos` esperado | Muestras: típicas / máximo |
|---|---|---|
| P1, P2, P5 | `[]`: no hay ruido | ±90–100 / 120–140 |
| P3 | Puede salir `[banda]`: la canción misma parece una banda | ±80 / 260 |
| P4 | `[]` | ±20 / 150: solo el chirp, una vez por segundo |

### Silencio (`0` en el emisor)

`tipos []` o algo suelto de `red_electrica`; muestras pequeñas (típicas ±13, máximo ≈ 30). No hay pulsos, así que tampoco referencia.

## La referencia limpia (para el MSE del nodo 3)

El nodo 1 guarda la señal limpia tal como llega al micrófono y la manda en cada trama, alineada con las muestras de la mezcla.

| Paso | Emisor | Nodo 1 (monitor a 921 600) | En este monitor |
|---|---|---|---|
| 1 | `p <n>`, `comp limpia` | `ref capturar 8` → a los ~9 s, `REF {"estado":"lista"...}` | `bytes` sube a ≈ 33 000 y aparece `(con referencia)` |
| 2 | `comp mezcla` | Nada (opcional: `ref` → `"aplica":true`) | `tipos` pasa a lo de la prueba; sigue `(con referencia)` |

| Situación | Qué se ve | ¿Normal? |
|---|---|---|
| Justo al cambiar `comp` | Un periodo con `tipos` raros (p. ej. `[impulsivo, tonal, banda]`) y una trama `0x00` sin referencia | ✔ El emisor reinicia la señal; al siguiente pulso todo vuelve |
| Se cambió de prueba (`p 1` → `p 2`) | Sigue `(con referencia)` pero es la de la prueba anterior | ✘ Volver a guardar la referencia con `comp limpia` |
| Se reinició el nodo 1 | `reinicios` sube y desaparece `(con referencia)` | Volver a guardarla |

### Cómo la usa el nodo 3

| Regla | Detalle |
|---|---|
| Calcular MSE y SNR solo si `estado & 0x40` | Saltar las tramas sin referencia |
| Dónde está | Después de las 1024 muestras: bytes 92 + 2048 en adelante, 1024 valores int16 en las mismas unidades que las muestras |
| Muestras sin referencia | Valor **−32768**: no usarlas en el MSE (pasa en P3, donde solo se guardan los primeros 2 s de la canción) |
| Qué es | La limpia capturada por el mismo parlante y micrófono. No compararse con el archivo de `pruebas/`: el parlante cambia el nivel de cada frecuencia y eso contaría como error |

## Datos para quien filtra

| Dato | Dónde (byte de la trama) | Uso |
|---|---|---|
| 1024 muestras int16 | 92 | La señal a filtrar |
| Tipos de ruido (bits) | 28 | bit 0 impulsivo, 1 red, 2 tonal, 3 banda |
| Confianza alta | 29, bit 0 | Con confianza baja, usar el filtro por defecto |
| Fin de la banda útil (float, Hz) | 32 | Corte del filtro adaptativo; NaN si la confianza es baja |
| Frecuencias interferentes (4 float) | 36 | Muescas del método espectral |
| Banda de ruido [inicio, fin] (2 float) | 52 | Banda a atenuar |

Formato completo: `nodo1/validacion/trama.py` y `nodo1/README.md`.

Dos cosas que aprendimos con este código y que el firmware real de los nodos 2 y 3 también necesita:

| Qué | Por qué |
|---|---|
| Leer la UART **por bloques** (`Serial1.read(buf, n)`), no de a un byte | Con la referencia llegan ≈ 65 KB/s; de a un byte el S3 no alcanza y se pierden tramas |
| Búfer de recepción grande (`Serial1.setRxBufferSize(16384)` antes de `begin`) | El de fábrica (256 B) se llena en menos de 3 ms |

## Resultado de referencia

P1 con la referencia guardada y el emisor en `comp mezcla` (5 de noviembre): 7–8 tramas válidas cada 0.5 s, 32 100–33 500 bytes, `0x40`/`0x48`, `tipos [tonal]` con 2508.0 Hz, y ningún CRC malo ni trama perdida nuevos en 30 s.
