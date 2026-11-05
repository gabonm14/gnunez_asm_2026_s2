# Nodo 1: qué debe hacer y cómo verificar la captura

Revisión de `nodo1/` (firmware `nodo1_esp32.ino`, scripts de `nodo1/validacion/`) frente a la especificación y al emisor actual (`emisor/`).

## Qué le toca al nodo 1

```
Emisor → parlante → aire → MAX4466 → RC → ADC (GPIO4) ──┐
Emisor GPIO27 (pulso de sincronización) ───────────────► nodo 1 → trama UART2 → nodos 2 y 3
```

Según la Figura 1 de la especificación, solo el nodo 1 recibe la entrada del sistema. Por eso también es el nodo 1 el que captura y guarda la referencia limpia para el MSE (ver "Referencia limpia para el MSE").

| Función | Sección | Qué significa |
|---|---|---|
| Capturar a 16 kHz | 1.1, 2 | Sin perder ni repetir muestras y sin recortar el ADC |
| Quitar la DC, Hann, FFT de 1024 | 1.1 | La FFT del MCU debe coincidir con NumPy (≤ 10⁻³) |
| Estimar el ruido | 1.1 | Tipo, frecuencias y banda; lo usan los nodos 2 y 3 |
| Enviar bloques y parámetros | 5.2, 5.3 | Trama con delimitador y CRC; avisar pérdidas y desbordamientos |
| Dar la referencia limpia | 3.5 | El MSE y la SNR necesitan s[n]; solo el nodo 1 la puede capturar |
| Anti-aliasing antes del ADC | 2 | Filtro físico y medido, no solo calculado |

El nodo 1 **no filtra**. El ruido del ambiente es parte del ruido real: no se elimina, se mide para saber cuánto pesa frente a la señal.

## Lo que ya está

| Parte | Estado |
|---|---|
| Captura | Temporizador a 16 kHz exactos, doble búfer de 1024, secuencia, marcas de tiempo |
| Avisos | Recorte (0 o 4095), muestras atrasadas, bloques perdidos, fs fuera de tolerancia, UART saturada |
| DC | Seguidor de DC muestra a muestra, sin escalones entre bloques |
| FFT y diagnóstico | Hann periódica, esp-dsp, PSD con 50 % de solapamiento; traducción de `src/diagnostico.py` |
| Trama | Delimitador, versión, secuencia, estado, parámetros del diagnóstico, 1024 muestras int16, CRC-32 |
| Validación sin placa | FFT ≤ 6.6·10⁻⁷, diagnóstico 21/21 frente a Python, tramas con fallas inyectadas |
| Scripts para la placa | `capturar.py` y `analizar_captura.py`: integridad, nivel, picos a ≤ 1 bin, respuesta del canal, piso de ruido, SNR con la limpia, repeticiones |
| Circuito de entrada | RC de dos etapas (corte 5.9 kHz), cálculo con la ganancia del MAX4466, procedimiento para medir el aliasing |

Todo lo validado es en la PC o simulado. Nada se ha medido en la placa.

## Cambios hechos según este documento

| # | Cambio | Dónde | Verificado en la PC |
|---|---|---|---|
| 1 | Verificación por espectros (Welch) | `nodo1/validacion/verificar_espectros.py` | Capturas simuladas de `caso_2` y `caso_3`: mezcla = limpia + ruido a 0.01 dB, SNR 2.02 y 2.04 dB, Parseval a 0.09 % |
| 2 | `IRAM_ATTR` y jitter en `adc` | Firmware | Ya estaba en el archivo, sin commit |
| 4 | Espectro del nodo para graficar (`espectro on`) | Firmware | Ya estaba en el archivo, sin commit |
| 8 | Pulso en GPIO35, `ref capturar`, referencia en la trama (versión 3) | Firmware, `trama.py`, `capturar.py` | `prueba_ref`: SNR con la referencia 5.382 dB frente a 5.381 reales; corrida 1 muestra, MSE 7.7 veces mayor; tramas con y sin referencia |
| 9 | Captura sin adaptador (`tramas_usb on`, `capturar.py --usb`) | Firmware, `capturar.py` | Solo en la placa |
| — | Pulso del emisor con ancho según la componente | `emisor/emisor.ino` | Compila |

Las pruebas que ya tenía el nodo siguen pasando: FFT ≤ 6.6·10⁻⁷, diagnóstico 21/21, tramas. El firmware compila para el ESP32 sin advertencias.

## Lo que falta

| # | Falta | Por qué importa | Propuesta |
|---|---|---|---|
| 1 | **Verificación por espectros** | `analizar_captura.py` calcula la SNR alineando en el tiempo, con retardo entero: medio muestra de error limita la SNR medida a ≈ 12 dB en 1320 Hz y ≈ 6 dB en 2508 Hz | Usar el método de la sección siguiente (Welch, sin alinear). Para el MSE, la alineación la da el pulso de GPIO27 |
| 2 | **Jitter del muestreo** | El ADC se lee en una tarea que despierta la interrupción; además `al_muestrear` usa `ARDUINO_ISR_ATTR`, que en el núcleo 3.x no la pone en IRAM. Un jitter de 1 µs limita la SNR a ≈ 36 dB en 2508 Hz; de 2 µs, a ≈ 30 dB | Usar `IRAM_ATTR` y reportar en `adc` la desviación entre el instante real de cada lectura y la rejilla de 62.5 µs (media, desviación, máximo) |
| 3 | **Piso de ruido frente al umbral de 40 dB** | El diagnóstico marca como ocupado todo lo que esté a menos de 40 dB del máximo. Si el piso de la sala o del ADC queda más arriba, aparece una "banda" falsa | Medir el piso (pasos 2 y 3 del plan) y, si hace falta, ajustar `set umbral` y justificar el valor |
| 4 | **Gráficas en vivo** | El profesor pide que la computadora solo muestre gráficas. Hoy el nodo envía muestras y un `DIAG` en texto; si la PC calcula la FFT para graficar, está procesando | Que el nodo envíe su propia PSD (513 valores en dB por periodo) y que la PC solo la grafique |
| 5 | **Distorsión del canal** | El parlante y el ADC agregan armónicos. Los de 2508 Hz (5016 Hz…) aparecerían como interferencias tonales extra; los de 440 Hz caen sobre 880 y 1320 | Verificar con `comp limpia` y `comp ruido` (pasos 4 y 5); documentar los armónicos si aparecen |
| 6 | **Impulsos después del parlante** | El parlante alarga cada impulso; la curtosis baja y el diagnóstico podría no detectar "impulsivo" | Verificar P4 con `comp ruido`: tipo impulsivo y ≈ 4 impulsos/s |
| 7 | **Ejemplos con `caso_1`** | Los ejemplos usan `caso_1` (2500 Hz), que el emisor no trae como prueba | Usar la tabla de correspondencia de abajo; `caso_1` se arma con `tonos` y `ruido tono 2500` |
| 8 | **Referencia limpia para el MSE** | El nodo 1 no guarda la limpia ni la envía; el nodo 3 no tiene contra qué calcular el MSE | Modo de referencia, entrada del pulso de sincronización y referencia en la trama (sección "Referencia limpia para el MSE") |
| 9 | **Adaptador USB-UART** | `capturar.py` lee las tramas de GPIO17 con un adaptador aparte | Capturar por el cable USB de la consola: `capturar.py --usb` |

El 2 limita cualquier SNR que se mida, por el método que sea.

## Método de verificación: espectros por componente (Welch)

El emisor emite una componente a la vez y el nodo 1 captura cada una por separado. La PSD de Welch no depende de la fase ni del retardo, así que las capturas no tienen que coincidir en el tiempo y **no hace falta enviar nada del emisor al nodo 1**: la componente se elige en el emisor con `comp` y se anota en la captura (`--nota`).

| Captura | Emisor | PSD |
|---|---|---|
| Sala | `0` | P_sala(f) |
| Limpia | `comp limpia` | P_limpia(f) |
| Ruido | `comp ruido` | P_ruido(f) |
| Mezcla | `comp mezcla` | P_mezcla(f) |

Las cuatro con la misma prueba, la misma distancia y la misma ganancia del micrófono, ≥ 10 s cada una.

| Verificación | Cálculo | Qué confirma |
|---|---|---|
| La mezcla es la esperada | P_mezcla ≈ P_limpia + P_ruido, banda por banda | Captura lineal, sin distorsión: señal y ruido son independientes, así que sus potencias se suman |
| SNR real en el micrófono | Σ(P_limpia − P_sala) / Σ(P_ruido − P_sala) | Sin alinear; sirve también en P5, donde se superponen |
| Peso del ambiente | Σ P_sala frente a Σ P_limpia y Σ P_ruido | Cuánto de la captura es ruido de la sala |
| Frecuencias | Picos de P_limpia y P_ruido | A ≤ 1 bin de lo configurado |
| Respuesta del canal | P_limpia / PSD de la limpia del caso digital | Atenuación del parlante y el micrófono en cada frecuencia |
| Escala de la FFT (Parseval) | Σx² = Σ\|X\|²/N en un bloque | FFT del nodo bien escalada; las potencias por banda se pueden sumar |

| No cubre | Por qué |
|---|---|
| MSE | Compara muestra a muestra: necesita alineación en el tiempo (sección siguiente) |
| Distorsión de fase y retardo | No se ven en la PSD; son métricas del nodo 3 |

La PSD la acumula ya el nodo 1 para el diagnóstico. Si se envía en la trama (falta 4), la computadora solo la grafica y compara.

## Referencia limpia para el MSE

La sección 3.5 calcula el MSE y la SNR "cuando se disponga de una referencia limpia s[n]". La del archivo no sirve: el parlante, la sala y el micrófono cambian la señal. La referencia tiene que pasar por el mismo canal, y la única entrada del sistema es el nodo 1.

### Conexión

| Emisor | Nodo 1 | Señal |
|---|---|---|
| GPIO27 | GPIO35 (solo entrada) | Pulso de 3.3 V al inicio de cada ciclo de la señal útil |
| — | GPIO35 → 100 kΩ → GND | GPIO35 no tiene pull interno: sin el cable, la entrada no flota |
| GND | GND | Común |

El ancho del pulso dice qué emite el emisor, y el nodo 1 solo guarda la referencia con el de 2 ms:

| Emisor | Pulso |
|---|---|
| `comp mezcla` | 1 ms |
| `comp limpia` | 2 ms |
| `comp ruido` | 3 ms |
| `0` (silencio) | Ninguno |

Es la única conexión entre el emisor y el nodo 1, además del sonido. No lleva datos: solo marca dónde empieza cada ciclo. Es coherente con la Figura 1, donde el emisor solo llega al nodo 1.

### Funcionamiento

| Paso | Emisor | Nodo 1 |
|---|---|---|
| 1. Referencia | `p <n>`, `comp limpia` | `ref capturar <k>`: espera el próximo pulso, suma k ciclos alineados con el pulso (k ≤ 8), los promedia y guarda un ciclo. Responde `REF {...}` al terminar |
| 2. Operación | `comp mezcla` | Captura la mezcla como siempre. En cada trama agrega el bloque de referencia que corresponde a esas muestras, según la posición dentro del ciclo que marca el pulso. |
| 3. Métricas | — | El nodo 3 calcula MSE, SNR y energía con las muestras y la referencia de la misma trama |

| Detalle | Valor |
|---|---|
| Ciclo | 1 s (16 000 muestras) en P1, P2, P4 y P5; 6 s en P3 |
| Memoria, int16 | Se reservan 64 KB (2 s) en el heap. Un ciclo de 1 s cabe entero; de P3 (6 s) se guardan los primeros 2 s y el MSE de P3 se calcula solo en ese tramo |
| Promedio de k ciclos | Baja el ruido de la sala en la referencia en 10·log₁₀(k) dB: 9 dB con k = 8. Máximo 8: la suma de 8 muestras de ±4095 cabe en int16 |
| Retardo parlante–micrófono | No hay que medirlo: la referencia y la mezcla se capturan por el mismo canal, con el mismo retardo respecto al pulso |
| Diferencia de relojes entre ESP32 | ≤ 40 ppm: ≤ 0.6 muestras por ciclo de 1 s. El pulso resincroniza en cada ciclo, así que no se acumula |
| Trama | Versión 3: cabecera de 92 bytes con la posición en el ciclo, la componente y el estado de la referencia; con referencia, +2048 bytes. 4192 bytes cada 64 ms, ≈ 71 % de 921 600 baudios |
| Fuera del ciclo guardado (P3, de 2 a 6 s) | La trama va sin referencia (o con −32768 en las muestras que no la tienen); el nodo 3 no calcula MSE ahí |
| Se cancela la captura | Si el periodo cambia, el pulso deja de ser de 2 ms o se pierden bloques. Responde `ERR ref cancelada: ...` |
| Cambio de prueba | Si el periodo cambia, la referencia deja de aplicarse sola. P1, P2, P4 y P5 duran 1 s: al cambiar entre ellas hay que volver a guardarla |

El emisor reinicia la señal en cada comando (`comp`, `p`, etc.), y el pulso siempre marca el inicio del ciclo nuevo, así que el nodo 1 no necesita saber qué comando se dio.

### Verificación

| Prueba | Criterio |
|---|---|
| `verificar_referencia.py` (sin placa o con `--puerto`) | `prueba_ref` cumple |
| Con `comp limpia` después de guardar la referencia (`verificar_referencia.py --captura`) | MSE ≈ 0 y SNR alta: solo queda el ruido de la sala. Ese valor es el techo de la SNR medible. |
| Con `comp ruido` | La "salida sin filtrar" menos la referencia es el ruido: SNR de entrada ≈ la medida con Welch |
| Pulsos por segundo | 1 en P1, P2, P4 y P5; 1 cada 6 s en P3 |
| Desplazar la referencia una muestra | El MSE debe subir: confirma que la alineación es la correcta |

## Correspondencia entre emisor y casos

| Prueba | Emisor | Caso de `pruebas/` | `--tonos` para analizar |
|---|---|---|---|
| P1 | `p 1` | `caso_7` | 440 2508 |
| P2 | `p 2` | `caso_2` | 440 880 1320 |
| P3 | `p 3` | `caso_5` | — |
| P4 | `p 4` | `caso_6` | — |
| P5 | `p 5` | `caso_3` | 440 880 1320 |
| Base en bin | `tonos 440:1 880:0.55 1320:0.3` + `ruido tono 2500` | `caso_1` | 440 880 1320 2500 |

Las fases de los tonos del emisor no son las del caso; el espectro sí es el mismo.

## Plan de verificación

Cada paso aísla una parte de la cadena. Si uno falla, el problema está entre ese paso y el anterior.

| Paso | Montaje | Emisor | Qué se verifica | Criterio |
|---|---|---|---|---|
| 1 | Nodo solo | — | `fuente sint`: FFT y diagnóstico en la placa; `validar_fft.py --adc`, `comparar_diagnostico.py` | FFT ≤ 10⁻³; diagnóstico igual a Python |
| 2 | Entrada del ADC fija en ≈ 1.65 V (divisor), sin micrófono | — | Piso eléctrico del ADC | Anotar RMS en dBFS; al menos 40 dB bajo el nivel de la señal |
| 3 | Micrófono, sala en silencio | `0` | Piso acústico de la sala | Igual que el 2; no debe haber picos fuertes (zumbido de 50/60 Hz) |
| 4 | Cable directo: GPIO25 → RC → GPIO4, GND común | `vol 0.5`, `p 1`, luego `comp limpia` y `comp ruido` | El nodo sin el canal acústico | Picos a ≤ 1 bin; con limpia, diagnóstico sin interferencias; con ruido, solo 2508 Hz |
| 5 | Por el aire | `p 1`, `comp limpia` | Señal útil después del canal | Pico en 440 Hz; anotar armónicos |
| 6 | Por el aire | `comp ruido` en P1, P2 y P4 | El ruido llega como se insertó | Tono 2508 Hz; banda 2500–3800 Hz; impulsivo ≈ 4/s |
| 7 | Por el aire | `comp mezcla`, P1–P5 | Captura y diagnóstico de cada prueba | Diagnóstico correcto e igual a Python con las mismas muestras |
| 8 | Por el aire | `0`, `comp limpia`, `comp ruido` y `comp mezcla`, misma prueba | Método por espectros | P_mezcla ≈ P_limpia + P_ruido; anotar la SNR real (no será exactamente 2 dB) |
| 8b | Por el aire, con GPIO27 → GPIO35 | `comp limpia` (guardar referencia), luego `comp mezcla` | Referencia limpia: `capturar.py --usb ... --ref 8`, que guarda la referencia y captura en la misma conexión (abrir el puerto de nuevo podría reiniciar la placa y borrarla) | Criterios de la sección "Referencia limpia para el MSE" |
| 9 | Tono externo de 12 kHz y de 4 kHz (teléfono) | `0` | Aliasing | Atenuación medida del alias (README del nodo) |

Con `vol 0.5` en el paso 4, el DAC queda entre ≈ 0.99 y 2.31 V, dentro del rango lineal del ADC (0.15–2.45 V).

En todos los pasos, durante la captura:

| Revisar | Comando | Debe dar |
|---|---|---|
| Recortes | `adc` | `muestras_recortadas` 0, `max_mv` < 2450, `min_mv` > 150 |
| Pérdidas | `adc` | `bloques_perdidos` 0, `tramas_descartadas` 0 |
| Atrasos | `adc` | `muestras_atrasadas` 0 |
| Duración | `capturar.py --segundos` | ≥ 10 s, 3 repeticiones por prueba (sección 4) |

## Números que conviene reportar

| Medición | De qué paso |
|---|---|
| Piso eléctrico y acústico (dBFS) | 2 y 3 |
| Margen entre la señal y el piso, frente al umbral de 40 dB | 3 y 5 |
| Respuesta del canal en 440, 880, 1320 y 2508 Hz | 5 y 6 |
| Armónicos que agrega el parlante | 5 y 6 |
| SNR real en el micrófono, por prueba, con media y desviación | 8 |
| Error de frecuencia de cada pico | 4 a 7 |
| Atenuación del alias | 9 |
| Jitter del muestreo, carga de CPU, memoria y latencia | `adc`, `tiempos`, `mem` |

## Ajuste del diagnóstico al hardware

Medido con el montaje final (parlante, MAX4466, ESP32): el canal agrega frecuencias que no se insertaron (intermodulación del parlante y de los convertidores, por ejemplo 2508 ± 440 Hz en P1) unos 35 dB bajo el componente más fuerte, y el ADC tiene tonos espurios propios. Con `umbral_ocupacion_db` = 40 el diagnóstico los reportaba como interferencias. Además, a la salida del parlante el tono de 2508 Hz es el componente más fuerte y, por caer entre dos bins, su lóbulo con Hann mide ≈ 109 Hz a −40 dB, más que el `ancho_linea_hz` de 100 Hz: salía como "banda".

| Parámetro (`metadatos/diagnostico.json` y valores por defecto del nodo 1) | Antes | Ahora |
|---|---|---|
| `umbral_ocupacion_db` | 40 | 30 |
| `ancho_linea_hz` | 100 | 125 |
| `separacion_impulsos_ms` (nuevo) | — (solo se agrupaban atípicas consecutivas) | 30 |

El parlante hace oscilar cada clic de P4 unos milisegundos y cada oscilación contaba como un impulso: el nodo estimaba ≈ 280–370/s con 4/s insertados. Medido en el nodo con P4 mezcla: con 10 ms, 13.4/s; con 30 ms, **5.9/s** (mediana 5; el inicio de cada chirp suma algunos eventos). En la simulación, con 30 ms el error medio de la tasa es 19 % (antes 0 %): con 10/s insertados se cuentan ≈ 7.5, porque dos impulsos a menos de 30 ms se cuentan como uno. El tipo detectado no cambia.

| Efecto | Resultado |
|---|---|
| Capturas reales, mezcla | P1: tonal en 2508 Hz (antes: 2068, 2948, 3696 y 4268 Hz); P2: banda ≈ 2400–4000 Hz (antes casi siempre "nada"); P4: impulsivo (igual) |
| Capturas reales, limpia | Sin interferencias falsas en P1 y P2 |
| Simulación (`src/diagnostico.py`) | Mismos aciertos de tipo en todo el barrido y en P6; error de borde de banda de 186/131/85 Hz a 85/30/64 Hz; `caso_5` pasa de "indeterminado" a "banda" 1422–7531 Hz (real 2000–7500) |
| Pipeline y pruebas | Métricas del pipeline sin cambios; 61/61 pruebas; nodo 1 igual a Python 21/21 |

## Decisiones pendientes del equipo

| Decisión | Detalle |
|---|---|
| Formato de la referencia en la trama | Propuesto en la trama versión 3 (`nodo1/validacion/trama.py`); confirmarlo con quien hace el nodo 3 |
| Distancia parlante–micrófono y ganancia del MAX4466 | Fijarlas y anotarlas en cada captura (`--nota`) |
| Pin del pulso en el nodo 1 | GPIO35 en el firmware; confirmar que esté libre en el montaje |
