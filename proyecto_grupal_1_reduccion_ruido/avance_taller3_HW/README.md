# Taller 3 — Punto 2: emisor en ESP32-S3

## Resumen del proyecto y del taller

El proyecto consiste en diseñar un sistema distribuido de reducción adaptativa de ruido que trabaje en tiempo real o cuasi real mediante microcontroladores conectados por comunicación alámbrica. Un nodo adquiere la señal contaminada y caracteriza su contenido mediante FFT; otra ruta aplica filtrado temporal FIR o IIR, mientras que una tercera utiliza FFT/IFFT para reducir el ruido y comparar los resultados mediante MSE, SNR, energía conservada y latencia. El procesamiento principal debe permanecer en los microcontroladores. El taller 3, correspondiente a la sesión asincrónica de la semana 12, prepara esta implementación: primero solicita prototipar el sistema completo en alto nivel y establecer sus frecuencias de trabajo; después, implementar en el microcontrolador el emisor seleccionado con frecuencias definidas; finalmente, elaborar los diagramas de la estrategia de validación del receptor. La entrega requiere documentar las decisiones de diseño y construcción, adjuntar los programas documentados y demostrar el funcionamiento en una defensa de diez minutos.

## Contexto y alcance

Documentos: `Apuntes_ASM_Semana12_Asincrónica_v6.pdf` y `Proyectos_ASM_Proyecto_Grupal1_v7.pdf`, suministrados por el estudiante. El primero no se titula literalmente «Taller 3»; se interpreta así por la solicitud.

Repositorio: https://github.com/gabonm14/gnunez_asm_2026_s2

- Base `development`, commit e4bbf1c4d01f7fbe4cfb433ede3252280d8a4c4e: `metadatos/configuraciones.json`, `docs/frecuencias.md`.
- Referencia adicional `feature/filtroIIR_Orquestador`, commit a784719ee84472d707240eb411c6b3c3c9e0d588: `metadatos/emisor.json`, `src/emisor.py`.
- Se implementa el emisor PWM del proyecto grupal, no el chirp del radar individual que también está en el repositorio.
- Hardware asumido: ESP32-S3. GPIO4 es una propuesta configurable; comprobar que esté disponible en la placa concreta. No se afirma que ese pin estuviera asignado en el proyecto.
- Este aporte cumple la implementación de software del punto 2. La demostración física sigue pendiente; tampoco sustituye los puntos 1 y 3 ni todo el informe PDF del taller.

## Instalación y ejecución

1. Arduino IDE: instalar **esp32 by Espressif Systems 3.3.2**; seleccionar **ESP32S3 Dev Module** y el puerto de la placa. El código está dirigido a esa versión (API Arduino 3.x/ESP-IDF 5.5); no a Arduino 2.x.
2. Abrir `emisor_esp32s3/emisor_esp32s3.ino`. Mantener `tablas.h` en la misma carpeta. No requiere biblioteca FFT ni generar tablas para cargarlo.
3. Si se utiliza USB nativo, configurar USB CDC On Boot según la conexión de la placa; con puente USB-UART, usar su puerto habitual.
4. Compilar y cargar. Abrir monitor serial a 115200 baudios. Arranca en reposo; escribir un dígito. `?` repite el menú.
5. Comenzar con ganancia baja en el amplificador. El cambio de modo puede producir un clic porque reinicia la fase; no usar ese transitorio para evaluar FFT.

| Comando | Salida |
|---|---|
| 0 | Reposo, duty 128: DC nominal de 1.65 V |
| 1 / 2 / 3 | Tono de 440 / 880 / 1320 Hz |
| 4 | Tres tonos, amplitudes relativas 1, 0.55, 0.3 y fases 0°, 35°, −50° |
| 5 / 6 / 7 | Tono de prueba de 2500 / 2508 / 3100 Hz |
| 8 | Tres tonos más interferencia de 2500 Hz, SNR digital previa a cuantización de 2 dB |

Los modos 5–7 son tonos aislados para caracterizar el emisor. En el modo 8 se suma la interferencia digitalmente; no reemplaza el banco de ruido completo del proyecto. La SNR física cambia con el filtro RC, el amplificador y el canal.

## Conexión

Filtro RC pasivo de dos etapas, igual al modelo de la rama del emisor:

| Elemento | Conexión |
|---|---|
| R1, 1 kΩ | GPIO4 a nodo A |
| C1, 10 nF cerámico | Nodo A a GND |
| R2, 1 kΩ | Nodo A a nodo B |
| C2, 10 nF cerámico | Nodo B a GND |
| Salida reconstruida | Nodo B respecto de GND; medir con alta impedancia |
| Audio | Nodo B a entrada del amplificador mediante acoplamiento AC; si el módulo ya lo incorpora, usarlo |
| Referencia | GND común entre ESP32 y entrada del amplificador |

Si el amplificador no incluye capacitor de entrada, añadir por ejemplo 1 µF no polarizado en serie y comprobar su impedancia de entrada: el corte de acople es 1/(2π Rin C). El capacitor elimina el sesgo de aproximadamente 1.65 V. La entrada del amplificador debe ser de alta impedancia para no alterar excesivamente el RC.

No conectar el parlante directamente al GPIO. Si se utiliza PAM8403, alimentar el módulo según sus especificaciones y conectar el parlante entre las dos salidas de un mismo canal, nunca de una salida a GND. El nivel admisible del parlante exige limitar la ganancia. La salida de potencia del amplificador no se conecta a un ADC. Para una conexión eléctrica al receptor, utilizar el nodo B con acondicionamiento y verificar el rango de entrada del ADC antes de conectarlo.

## Justificación y funcionamiento

- Frecuencia de muestras: 16 kHz. Un temporizador de 2 MHz genera una alarma cada 125 cuentas: periodo de 62.5 µs exacto en cuentas del reloj. No se usan `delayMicroseconds(62)` ni la consola como reloj.
- PWM: 256 kHz objetivo, 8 bits. Se fuerza APB de 80 MHz. La frecuencia real queda cuantizada por el divisor; el programa imprime la informada por el driver (aproximadamente 256.4 kHz). No confundir portadora con tono audible ni con frecuencia de muestras.
- Señales: tonos y proporciones del repositorio. Se limita el pico digital a 0.8; la mezcla se escala conjuntamente para conservar su SNR antes de cuantizar.
- Cuantización: `round((x+1)*127.5)`, con códigos 25–230 en las tablas generadas. El duty físico es código/256, no código/255; por ello el voltaje debe evaluarse usando el primer cociente.
- Tablas: 4000 muestras por modo (0.25 s). Todos los tonos completan un número entero de ciclos, incluido 2508 Hz. La tabla periódica evita un salto artificial al volver al inicio. La longitud de síntesis NO cambia el N=1024 de la FFT del receptor.
- RAM: 36000 bytes para nueve tablas, copiadas antes de iniciar las interrupciones. La ISR no calcula senos, imprime, reserva memoria ni accede a las tablas de flash. Actualiza LEDC mediante funciones LL del ESP32-S3; esta dependencia de bajo nivel requiere mantener la versión indicada y revisar al migrar.
- El canal LEDC 0 y temporizador LEDC 0 quedan reservados. La escritura LL es exclusiva de la ISR tras configurar el canal. Los cambios de modo están protegidos con sección crítica.
- El temporizador de muestras y la portadora no están sincronizados: la aplicación efectiva del duty tiene una incertidumbre asociada al periodo PWM. Se debe medir además el jitter de interrupciones; no habilitar Wi-Fi/Bluetooth ni operaciones de flash durante esta prueba.

Para las dos etapas RC sin buffer, la carga entre etapas produce:

`H(s) = 1 / (R1*C1*R2*C2*s² + (R1*C1 + R2*C2 + R1*C2)*s + 1)`.

Con los valores indicados, el denominador es `1e-10*s² + 3e-5*s + 1`. No es correcto tratarlas como dos filtros independientes idénticos. El RC reconstruye el PWM, pero no demuestra por sí solo que el receptor esté protegido contra aliasing; el acondicionamiento y antialias del ADC se deben validar aparte.

## Verificación realizada y pruebas físicas pendientes

Ejecutar `python generar_tablas.py` con NumPy instalado regenera las tablas y `validacion_digital.json`. Se verificaron los bytes exportados, el rango de códigos, las seis frecuencias mediante FFT, la presencia de los tres componentes y la SNR de la mezcla antes de cuantizar. Es evidencia numérica del emisor, no evidencia experimental.

No se ha compilado con el toolchain de ESP32 ni cargado en una placa desde este entorno. La compilación y las mediciones siguientes son necesarias antes de afirmar cumplimiento físico del punto 2:

1. Compilar con la versión indicada y registrar la versión del core y la placa.
2. En reposo, medir aproximadamente 1.65 V en B y la portadora en GPIO4; comparar con lo reportado por consola.
3. Probar modos 1–3: comprobar frecuencia en osciloscopio o captura del receptor. Criterio propuesto: error menor al 1 % medido con resolución suficiente.
4. Probar modo 4 y observar los tres picos. Con fs=16 kHz, N=1024 y Hann, el espaciado FFT es 15.625 Hz; aceptar localización dentro de un bin, sin exigir que 440 Hz sea bin exacto.
5. Probar 2500 Hz (bin exacto), 2508 Hz (fuera de bin) y 3100 Hz. Esperar fuga espectral en los dos últimos y documentarla.
6. Probar modo 8; retirar DC al analizar. No exigir SNR analógica de 2 dB: medir el efecto de RC y canal.
7. Mantener cada modo al menos 10 s, observar discontinuidades, saturación y jitter; guardar las capturas reales. Evaluar estabilidad antes de integrar otros nodos.

## Referencias técnicas

- Espressif, LEDC ESP32-S3: https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32s3/api-reference/peripherals/ledc.html
- Espressif, Arduino Timer API: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/timer.html
- Espressif, LL LEDC (fuente consultada): https://github.com/espressif/esp-idf/blob/v5.5.1/components/hal/esp32s3/include/hal/ledc_ll.h

Preparado con asistencia de IA para implementación, documentación y verificación numérica. Revisar cada línea antes de la defensa y registrar esta ayuda en la sección de herramientas del proyecto.
