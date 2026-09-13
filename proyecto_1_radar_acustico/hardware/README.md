# Hardware e integración - Radar acústico

## 1. Objetivo

Esta carpeta contiene la información correspondiente al hardware del sistema
de radar acústico.

El sistema físico debe ser capaz de:

1. Generar una señal acústica conocida.
2. Reproducirla mediante un parlante o transductor.
3. Capturar la señal directa y los ecos mediante un micrófono.
4. Digitalizar la señal recibida mediante ADC.
5. Procesar las muestras mediante FFT.
6. Detectar el eco mediante correlación.
7. Estimar el tiempo de vuelo.
8. Calcular la distancia.
9. Mostrar el resultado mediante terminal serial.

---

# 2. Arquitectura general propuesta

La arquitectura inicial será:

```text
                         OBJETO
                           │
                           │ reflexión
                           ▼
                     ┌───────────┐
                     │ Micrófono │
                     └─────┬─────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Preamplificador │
                  │ / acondicionador│
                  └────────┬────────┘
                           │
                           ▼
                         ADC
                           │
                           ▼
                    ┌────────────┐
                    │            │
                    │    ESP32   │
                    │            │
                    └─────┬──────┘
                          │
                   DAC / PWM / I2S
                          │
                          ▼
                   ┌─────────────┐
                   │ Amplificador│
                   └──────┬──────┘
                          │
                          ▼
                      Parlante
```

El ESP32 es actualmente el microcontrolador candidato, pero el diseño
definitivo dependerá del modelo exacto disponible.

---

# 3. Componentes propuestos

## Elementos principales

- 1 microcontrolador ESP32.
- 1 micrófono o módulo de micrófono con salida adecuada para ADC.
- 1 preamplificador o módulo de micrófono amplificado.
- 1 parlante pequeño.
- 1 amplificador de audio para el parlante.
- Protoboard.
- Jumpers.
- Cable USB.
- Resistencias y capacitores necesarios para acondicionamiento.

## Opcionales para pruebas

- Osciloscopio.
- Multímetro.
- Fuente externa.
- Generador de funciones.

---

# 4. Consideraciones importantes

## Parlante

El parlante NO debe conectarse directamente a un GPIO del microcontrolador.

La salida del microcontrolador debe pasar por una etapa apropiada de
generación de señal y posteriormente por un amplificador.

Dependiendo del ESP32 seleccionado se podrá utilizar:

- DAC interno, si el modelo dispone de él;
- PWM filtrado;
- I2S con DAC externo.

La decisión final se tomará cuando se conozca el modelo exacto del ESP32.

## Micrófono

El micrófono debe entregar una señal compatible con el rango de entrada del ADC.

Un micrófono electret sin acondicionamiento no debe conectarse directamente
al ADC. Se requiere polarización y amplificación o un módulo que ya incorpore
estas funciones.

---

# 5. Parámetros utilizados actualmente en software

Los siguientes valores fueron utilizados durante las simulaciones:

```text
Frecuencia de muestreo:
FS = 48000 Hz

Chirp:
f_inicio = 2000 Hz
f_final  = 10000 Hz
duración = 10 ms

Velocidad del sonido utilizada:
343 m/s

Duración de adquisición simulada:
50 ms

Distancia mínima utilizada para eliminar la señal directa:
0.20 m
```

IMPORTANTE:

Estos parámetros son actualmente valores de diseño utilizados en simulación.

No deben considerarse definitivos hasta comprobar que:

- el micrófono responde correctamente en el rango utilizado;
- el parlante reproduce adecuadamente esas frecuencias;
- el ADC permite mantener la frecuencia de muestreo seleccionada;
- el microcontrolador puede realizar el procesamiento requerido.

Si algún parámetro cambia en hardware, debe modificarse también en el software
de procesamiento y en la documentación.

---

# 6. Software desarrollado actualmente

El procesamiento de referencia está implementado en Python.

## `src/python/signals.py`

Contiene la generación matemática del chirp lineal.

Implementa una señal del tipo:

x(t) = sin(2*pi*(f0*t + 0.5*k*t^2))

donde:

k = (f1 - f0) / T

Esta implementación servirá como referencia para generar la misma señal en
el microcontrolador.

---

## `src/python/dft.py`

Implementación directa de la Transformada Discreta de Fourier.

Se utiliza principalmente con fines experimentales y para comparar la
complejidad frente a FFT.

No se recomienda utilizar la DFT directa en el sistema final debido a su
alto costo computacional.

---

## `src/python/fft.py`

Contiene:

- FFT radix-2.
- IFFT.

Esta implementación sirve como referencia matemática para el procesamiento
que posteriormente deberá ejecutarse en el microcontrolador.

En el microcontrolador podrá utilizarse:

- una adaptación de este algoritmo;
- o una biblioteca DSP/FFT apropiada para el microcontrolador.

Los resultados obtenidos deberán validarse contra la implementación de Python.

---

## `src/python/correlation.py`

Contiene dos algoritmos:

1. Correlación directa.
2. Correlación mediante FFT.

La implementación mediante FFT es la candidata principal para el sistema final.

---

## `experiments/echo_detection/echo_simulation.py`

Este archivo es solamente una simulación.

Genera artificialmente:

- señal directa;
- eco principal;
- reflexión secundaria;
- ruido.

NO forma parte del firmware final.

---

## `experiments/echo_detection/direct_correlation.py`

Demuestra la detección de distancia mediante correlación directa.

Se utiliza como referencia experimental.

---

## `experiments/echo_detection/fft_correlation.py`

Demuestra la detección del eco mediante correlación por FFT.

Esta implementación representa mejor el procesamiento que se desea trasladar
al microcontrolador.

---

# 7. Integración hardware-software

La integración se realizará en varias etapas.

## Etapa 1 - Generación de señal

El microcontrolador debe generar el mismo chirp utilizado en Python.

Parámetros iniciales:

```text
fs = 48000 Hz
f0 = 2000 Hz
f1 = 10000 Hz
duración = 10 ms
```

Primero se debe comprobar únicamente:

```text
ESP32
  │
  ▼
salida de señal
  │
  ▼
amplificador
  │
  ▼
parlante
```

Se debe verificar que el chirp realmente pueda reproducirse.

---

# 8. Etapa 2 - Adquisición

Después se debe probar únicamente el receptor:

```text
Micrófono
    │
    ▼
Preamplificador
    │
    ▼
ADC del ESP32
    │
    ▼
buffer de muestras
```

El ADC debe adquirir muestras a una frecuencia estable.

La frecuencia objetivo inicial es:

```text
48000 muestras/s
```

El firmware debe almacenar las muestras en un buffer.

Durante esta etapa todavía NO es necesario implementar FFT.

---

# 9. Primera conexión con Python

Durante las pruebas iniciales el ESP32 puede enviar las muestras adquiridas
por USB/Serial hacia la computadora.

Ejemplo conceptual:

```text
ESP32
 │
 │ USB Serial
 ▼
Computadora
 │
 ▼
Python
 │
 ├── FFT
 ├── correlación
 └── estimación de distancia
```

Esto permitirá comprobar primero que el hardware está capturando correctamente
los ecos.

IMPORTANTE:

Este modo será utilizado únicamente para desarrollo y validación.

El sistema final deberá ejecutar el procesamiento requerido en el
microcontrolador.

---

# 10. Formato provisional para enviar muestras

Durante las primeras pruebas se recomienda enviar algo sencillo por serial.

Ejemplo:

```text
START
2048
2035
2028
2010
...
END
```

Cada número corresponde a una muestra del ADC.

También se puede enviar:

```text
FS=48000
N=2400
START
...
END
```

De esta forma Python puede reconstruir exactamente la señal capturada.

---

# 11. Etapa 3 - Validación con datos reales

Una vez que el ESP32 pueda capturar la señal:

1. Colocar un objeto a una distancia conocida.
2. Transmitir el chirp.
3. Capturar las muestras.
4. Enviar las muestras al computador.
5. Guardarlas en:

```text
data/measured/
```

Ejemplo:

```text
data/measured/
├── 050cm.csv
├── 100cm.csv
├── 150cm.csv
└── 200cm.csv
```

Posteriormente el código Python debe aplicar:

```text
muestras reales
      │
      ▼
     FFT
      │
      ▼
 correlación
      │
      ▼
    retardo
      │
      ▼
   distancia
```

Esto permitirá determinar si el problema está en:

- hardware;
- adquisición;
- generación del chirp;
- o algoritmo de procesamiento.

---

# 12. Etapa 4 - Procesamiento dentro del ESP32

Cuando las mediciones reales funcionen correctamente en Python, se trasladará
el procesamiento al firmware.

El flujo final debe ser:

```text
generar chirp
      │
      ▼
reproducir chirp
      │
      ▼
capturar ADC
      │
      ▼
buffer de muestras
      │
      ▼
     FFT
      │
      ▼
correlación FFT
      │
      ▼
buscar pico
      │
      ▼
retardo en muestras
      │
      ▼
tiempo de vuelo
      │
      ▼
distancia
      │
      ▼
Serial
```

---

# 13. Conversión del retardo a distancia

Si el pico de correlación aparece en la muestra:

```text
delay_samples
```

el tiempo de vuelo será:

```text
tau = delay_samples / fs
```

y la distancia:

```text
distance = speed_of_sound * tau / 2
```

Por tanto:

```text
distance =
speed_of_sound * delay_samples
--------------------------------
            2 * fs
```

El firmware deberá realizar este cálculo directamente.

---

# 14. Salida final del sistema

Para reducir hardware adicional, inicialmente se utilizará la terminal serial.

Ejemplo:

```text
-----------------------------
RADAR ACUSTICO
-----------------------------
Retardo: 281 muestras
Tiempo: 5.854 ms
Distancia: 1.004 m
-----------------------------
```

No es necesario utilizar pantalla LCD u OLED mientras la terminal serial sea
aceptada como visualización.

---

# 15. Funciones propuestas para el firmware

La estructura conceptual del firmware puede ser:

```text
setup_hardware()

generate_chirp()

transmit_chirp()

capture_audio()

compute_fft()

compute_correlation()

detect_echo()

calculate_distance()

print_result()
```

El ciclo principal sería aproximadamente:

```text
Inicializar sistema

while true:

    generar/transmitir chirp

    adquirir muestras

    ejecutar FFT

    calcular correlación

    buscar eco

    calcular distancia

    mostrar resultado

    esperar siguiente medición
```

---

# 16. Organización propuesta del firmware

Cuando se defina el microcontrolador exacto se recomienda crear:

```text
src/
└── firmware/
    ├── README.md
    ├── main.cpp
    ├── signal_generator.cpp
    ├── signal_generator.h
    ├── acquisition.cpp
    ├── acquisition.h
    ├── dsp.cpp
    └── dsp.h
```

La estructura puede cambiar dependiendo del framework elegido.

---

# 17. Pruebas mínimas de hardware

Antes de integrar todo deben completarse estas pruebas.

## Generación

- [ ] Microcontrolador enciende correctamente.
- [ ] Puede generar una señal periódica.
- [ ] Puede generar el chirp.
- [ ] El amplificador recibe la señal.
- [ ] El parlante reproduce la señal.

## Recepción

- [ ] Micrófono funciona.
- [ ] La salida del micrófono está dentro del rango permitido por el ADC.
- [ ] ADC entrega valores estables.
- [ ] Se mantiene aproximadamente la frecuencia de muestreo seleccionada.
- [ ] Las muestras pueden almacenarse en memoria.

## Comunicación

- [ ] El microcontrolador puede enviar las muestras por serial.
- [ ] La computadora puede guardar las muestras.
- [ ] Python puede procesar las muestras reales.

## Radar

- [ ] Se identifica la transmisión directa.
- [ ] Se observa un eco.
- [ ] El retardo cambia cuando se mueve el objeto.
- [ ] Python calcula correctamente la distancia.
- [ ] El algoritmo funciona dentro del microcontrolador.
- [ ] La distancia se muestra por serial.

---

# 18. Mediciones que deben documentarse

Guardar evidencia de al menos varias distancias conocidas.

Ejemplo:

```text
Distancia real | Distancia estimada | Error
---------------|--------------------|------
0.50 m         |                    |
1.00 m         |                    |
1.50 m         |                    |
2.00 m         |                    |
```

Para cada prueba guardar:

- distancia real;
- distancia estimada;
- retardo detectado;
- frecuencia de muestreo;
- imagen o captura;
- observaciones.

---

# 19. Información que debe registrar la persona encargada del hardware

Cuando se seleccionen los componentes, documentar:

```text
Microcontrolador:
Modelo:

Micrófono:
Modelo:

Amplificador del micrófono:
Modelo:

Parlante:
Modelo:
Impedancia:

Amplificador de parlante:
Modelo:

Frecuencia de muestreo real:

Método de salida:
DAC / PWM / I2S

Método de adquisición ADC:

Pines utilizados:

Voltajes utilizados:
```

No definir pines hasta conocer el modelo exacto del microcontrolador.

---

# 20. Responsabilidades de hardware

La persona encargada del hardware debe dejar funcional:

```text
GENERACIÓN
ESP32 -> amplificador -> parlante

RECEPCIÓN
micrófono -> acondicionamiento -> ADC -> ESP32

ADQUISICIÓN
ESP32 -> buffer de muestras

VALIDACIÓN
ESP32 -> Serial -> computadora
```

Una vez que estos bloques funcionen, se realizará conjuntamente la integración
con el procesamiento FFT y correlación.

---

# 21. Estado actual

## Software

- [x] DFT
- [x] FFT radix-2
- [x] IFFT
- [x] Magnitud y fase
- [x] Chirp
- [x] Simulación de ecos
- [x] Correlación directa
- [x] Correlación mediante FFT
- [x] Estimación de retardo
- [x] Cálculo de distancia
- [x] Comparación de tiempos

## Hardware

- [ ] Seleccionar microcontrolador definitivo
- [ ] Seleccionar micrófono
- [ ] Seleccionar parlante
- [ ] Seleccionar amplificador
- [ ] Probar generación
- [ ] Probar adquisición
- [ ] Capturar primeras muestras reales
- [ ] Integrar procesamiento
- [ ] Realizar mediciones finales