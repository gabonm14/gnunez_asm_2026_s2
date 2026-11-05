# Cambios en el emisor y el nodo 1 (3–4 de noviembre de 2026)

Resumen para quienes trabajan en los nodos 2 y 3 y en el paper. El detalle de la verificación está en `docs/nodo1_verificacion.md`.

## Lo que afecta a los nodos 2 y 3

| Cambio | Detalle | Qué hacer |
|---|---|---|
| Trama **versión 3** | Cabecera de 92 bytes (antes 84). Nuevos campos 84–91: posición en el ciclo del emisor, inicio de ciclo en el bloque, componente que emite el emisor y estado de la referencia. Si el estado trae el bit 6 (`referencia`), después de las 1024 muestras vienen 1024 valores int16 de la referencia limpia (−32768 = sin referencia en esa muestra). | Leer la versión 3. Decodificador de referencia: `nodo1/validacion/trama.py`; en C++, `receptor_byte` del `.ino` del nodo 1 |
| Referencia limpia para el MSE | El nodo 1 guarda un ciclo de la señal limpia tal como llega al micrófono (promedio de hasta 8 ciclos) y la manda en cada trama junto a las muestras de la mezcla | El nodo 3 calcula MSE y SNR con las muestras y la referencia de la misma trama |
| Conexión | GPIO17 del nodo 1 (TX) → RX del otro ESP32, GND común, 921 600 baudios, 8N1 | — |
| Parámetros del diagnóstico | `umbral_ocupacion_db` 40 → **30**, `ancho_linea_hz` 100 → **125** y nuevo `separacion_impulsos_ms` = **30** en `metadatos/diagnostico.json`; la simulación ya se regeneró | Usar el JSON actualizado |
| Ruido de P2 dentro de la banda útil | El parlante intermodula la banda de 2500–3800 Hz y genera ruido de 30 a 1300 Hz, 13–17 dB sobre la sala. Por eso el nodo 1 da confianza baja en P2: el ruido sí se superpone a la señal útil | Un pasa altos digital de ≈ 300 Hz en los nodos 2 y 3 quitaría la parte de 30–400 Hz (la útil empieza en 440 Hz) |
| SNR real en el micrófono | No es 2 dB: de −8 a +1 dB según la prueba (tabla abajo) | Las métricas de entrada parten de esos valores |

## Emisor (`emisor/`)

| Cambio | Antes | Ahora | Por qué |
|---|---|---|---|
| Señal útil de P4 | Pulso rectangular de 50 ms | **Chirp 600 → 1400 Hz**, 50 ms cada 1 s, envolvente Tukey | Del pulso rectangular el parlante deja pasar ≈ 1 % de la energía; del chirp, 97–99 %. También en la simulación (`caso_6`) |
| Comando | `pulso <ms> <periodo_s>` | `chirp <f0> <f1> <ms> <periodo_s>` | — |
| Pulso de sincronización (GPIO27) | 1 ms siempre | Ancho según la componente: **1 ms mezcla, 2 ms limpia, 3 ms ruido**; sin pulsos en silencio | El nodo 1 sabe qué emite el emisor y solo guarda la referencia con la limpia |
| Vaciados del búfer al cambiar de prueba | Se contaban al cambiar de modo | El primer bloque se calcula antes de vaciar; el contador se reinicia en cada cambio | — |

## Nodo 1 (`nodo1/`)

| Cambio | Detalle |
|---|---|
| Entrada del micrófono | **GPIO4** (ADC2_CH0), antes GPIO34. El ADC2 no funciona con WiFi; el nodo no lo usa. Para volver: `PIN_ADC`, `UNIDAD_ADC` y `CANAL_ADC` en el `.ino` |
| Pulso del emisor | GPIO35 (solo entrada), con 100 kΩ a GND |
| Referencia | `ref capturar <k>`, `ref`, `ref borrar`, `prueba_ref` |
| Captura sin adaptador | `tramas_usb on/off`: copia de cada trama por el USB; `capturar.py --usb PUERTO`. GPIO17 sigue enviando |
| Jitter y lecturas fallidas | `adc` informa el jitter del muestreo y las lecturas del ADC con error |
| Scripts nuevos | `validacion/verificar_espectros.py` (Welch por componente), `validacion/verificar_referencia.py`, `prueba_microfono/prueba_microfono.ino` |
| `capturar.py` | `--usb`, `--ref K`, `--simular CASO --componente limpia\|ruido\|contaminada`; abre el puerto sin reiniciar la placa |

## Montaje final medido

```
Emisor GPIO25 → atenuador → PAM8403 (potenciómetro al máximo) → parlante 8 Ω 0.5 W
     ~ 10 cm de aire ~
MAX4466 (ganancia al máximo, VCC con filtro RC) OUT ── 2 × 100 nF ──┬── R1 ──┬── R2 ──┬──► GPIO4
                                                   3V3 ── 10 kΩ ───┤       C3       C4
                                                   GND ── 5.1 kΩ ──┘       GND      GND
Emisor GPIO27 ───────────────────────────────────────────────────────────────────────► GPIO35
```

| Elemento | Valor | Por qué |
|---|---|---|
| High-pass a la entrada | 200 nF (2 × 100 nF) en serie, 10 kΩ a 3V3 y 5.1 kΩ a GND: corte ≈ 235 Hz, bias ≈ 1.1 V | Quita el zumbido de 60 Hz que capta el micrófono (−15 dB) y da más margen al ADC hacia arriba |
| Anti-aliasing | R1-C3-R2-C4 de dos etapas (corte ≈ 5.9 kHz), **con su tierra en el GND del ESP32** | Con la tierra compartida con otros cables metía un siseo de banda ancha (+27 dB) |
| Tierras | Todas las del micrófono y sus filtros juntas en el nodo 1, cables cortos | — |
| Distancia y volumen | 10 cm, `vol 1` | Más cerca o más fuerte, el parlante distorsiona |

| Medición | Antes de los arreglos | Montaje final |
|---|---|---|
| 60 Hz bajo el tono de 440 Hz | 10 dB | 33 dB |
| Piso por bin, en silencio | −65 dBFS | −79 dBFS |
| Mezcla en el ADC | Hasta 2971 mV (saturaba) | 600–1540 mV |

## Resultados de las capturas finales (10 cm, `vol 1`)

| Prueba | Mezcla = limpia + ruido − sala | SNR real en el micrófono | Diagnóstico del nodo 1 en la mezcla |
|---|---|---|---|
| P1 | No (7.7 dB): intermodulación del parlante, p. ej. 3388 Hz | −7.9 dB | Tonal en 2508 Hz (+ 3388 Hz del parlante) |
| P2 | Sí (0.46 dB) | −7.6 dB | Banda ≈ 2400–4100 Hz |
| P3 | Sí (0.45 dB) | −2.0 dB | Variable, como en la simulación |
| P4 | Sí (0.39 dB) | +1.2 dB | Impulsivo |
| P5 | Sí (0.12 dB) | −2.3 dB | Banda ≈ 844–1906 Hz |

Diagnóstico del nodo 1 igual al de Python sobre las mismas muestras: 55/55 periodos.

## Pendiente

| Pendiente | Responsable |
|---|---|
| 3 repeticiones de cada prueba con el montaje final (sección 4 de la especificación) | Nodo 1 |
| Probar la salida por GPIO17 (puente GPIO17 → GPIO16 y `rx`) | Nodo 1 |
| Probar la referencia en la placa (`capturar.py --usb ... --ref 8`) | Nodo 1 |
| Leer la trama versión 3 y calcular MSE/SNR con la referencia | Nodos 2 y 3 |
| Subir estos cambios a una rama | Equipo |
