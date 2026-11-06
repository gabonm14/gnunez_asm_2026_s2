# Captura y gráficas de los nodos 2 y 3

Esta versión guarda la referencia limpia, la mezcla y las dos salidas filtradas del mismo intervalo. El ESP32-S3 calcula el MSE, la SNR, la energía útil y los espectros. El programa de Python recibe las muestras y los resultados, guarda los archivos y dibuja las figuras. El puerto de la computadora trabaja a **115200 baudios**, con **USB CDC On Boot en Disabled**, como en tu montaje. UART1 recibe al nodo 1 por GPIO16 a 921600 baudios.

## 1. Cargar el firmware

Abrí `nodos23/nodos23.ino` con todos los archivos de su carpeta juntos. Usá **ESP32S3 Dev Module**, paquete **esp32 by Espressif Systems 3.3.2**, **USB CDC On Boot → Disabled** y **Core Debug Level → None**. Instalá Adafruit SSD1306, Adafruit GFX Library y Adafruit BusIO. Cargá el sketch por el puerto que ya te funciona.

Las salidas son GPIO17 para FIR y GPIO18 para FFT. El selector se lee en GPIO7 y la OLED usa SDA=8/SCL=9. Se conserva el método de escucha de un clip mediante `p` y el selector A/B.

Ahora se reservan ocho bytes por instante para cuatro valores int16. Eso equivale a 128 000 bytes/s. La consola informa la capacidad real al arrancar. La duración será aproximadamente la mitad de la versión anterior, algo menor por la memoria de los espectros. Usá la duración que muestre tu placa como dato de la toma. El clip se pierde al reiniciar o al empezar otra grabación.

## 2. Preparar Python en Windows

Descomprimí el ZIP y abrí PowerShell en esa carpeta. Ejecutá una vez lo siguiente.

```powershell
python -m pip install -r requirements.txt
```

Listá los puertos para identificar el del S3.

```powershell
python capturar_graficas.python --puertos
```

Cerrá el monitor serie **del S3** en Arduino IDE. El monitor del nodo 1 puede continuar abierto para controlar la referencia. Cada equipo debe usar su propio puerto COM. En los comandos siguientes reemplazá `COM3` por el puerto del S3.

## 3. Primera captura de P3

Iniciá el programa antes de grabar. Así la conexión permanece abierta durante la captura y la descarga. Algunos puentes USB-UART pueden reiniciar la placa al abrir el puerto. El programa configura DTR/RTS antes de abrirlo y espera el arranque.

```powershell
python capturar_graficas.python --puerto COM3 --prueba P3 --repeticion 1
```

Python mostrará la capacidad, si están llegando tramas y si la última trama tiene referencia. Quedará esperando Enter. Mientras tanto, prepará la prueba con los otros dos equipos.

1. En el **emisor**, enviá `p 3` y luego `comp limpia`.
2. En el **nodo 1**, enviá `ref capturar 8`. Esperá a que confirme que la referencia está `lista`.
3. En el **emisor**, enviá `comp mezcla`. Esperá unos dos segundos para que se estabilice el diagnóstico.
4. Volvé a PowerShell y presioná **Enter**. Python enviará `r` al S3. Este esperará contexto completo con referencia válida, grabará un tramo continuo, pasará a `LISTA` y Python solicitará la exportación con `x`.
5. Esperá a que termine la descarga. Para un clip de alrededor de 1,5 s, puede tomar unos 20 segundos a 115200 baudios. A continuación se guardan automáticamente las gráficas y los CSV.

El firmware de este paquete se identifica como **nodos23-export-2**. Hay que cargarlo y reemplazar también el script Python. La captura normal ya no ofrece continuar sin referencia: espera hasta que llegue. Si se acaba la referencia antes de llenar la RAM, conserva el tramo continuo y finaliza con `Fin tramo referencia`. La duración puede ser inferior a la capacidad. No une segmentos de ciclos diferentes. Un tramo menor que 1024 muestras no alcanza para el espectro: repetí la toma.

`ref capturar 8` solicita ocho **ciclos**, no ocho segundos. Esperá la confirmación `lista` del nodo 1. Después de `comp mezcla`, enviá `ref` en el nodo 1: revisá `estado`, `aplica`, `sincronia` y `motivo`. En la versión de nodo 1 revisada se guardan como máximo los primeros dos segundos del ciclo; por eso una trama sin referencia por sí sola no demuestra que la preparación haya fallado. El S3 espera un tramo válido real.

Si no termina dentro de 90 segundos de espera más 15 de margen, Python detiene la captura e informa el problema. Podés ampliar con `--espera-referencia 180`. Si sigue sin llegar referencia, conservá la salida completa de `ref` después de pasar a mezcla para revisar nodo 1. La espera no crea una referencia ni corrige una sincronía ausente.

Para una captura deliberadamente sin exigir referencia usá `--sin-referencia`. En ese modo las métricas pueden ser N/D. No utilices esa toma como comparación cuantitativa con señal limpia.

### Escuchar después de descargar

Al terminar de guardar, Python mantiene COM3 abierto y muestra `Escucha [p/s/salir]`. Silenciá el emisor antes de escuchar. Escribí `p` y Enter para reproducir el clip filtrado desde el inicio; el selector físico permite escuchar FIR o FFT con el PAM. `s` detiene y `salir` detiene y cierra el puerto. Al finalizar un clip podés enviar `p` otra vez. No abras el monitor serie del S3 durante esta sesión.

La reproducción usa la captura guardada; no vuelve a grabar el sonido del parlante. El clip está en RAM y se pierde al reiniciar. La opción `--sin-escucha` termina el programa al guardar. Al reabrir el puerto, algunas placas reinician: para escuchar la misma toma, usá el menú de la sesión actual.

La opción `--prueba P3` etiqueta los resultados. Seleccioná también P3 en el emisor. Para la segunda y tercera toma usá `--repeticion 2` y `--repeticion 3`. Las carpetas incorporan fecha y hora para conservar cada toma por separado.

## 4. Archivos generados

Cada ejecución crea una carpeta dentro de `resultados/` con estos archivos.

| Archivo | Contenido |
|---|---|
| `senales_tiempo.png` y `.pdf` | Mezcla, FIR y FFT comparados con la referencia limpia. Vista completa y detalle de 20 ms con la misma escala de amplitud. |
| `espectros_metricas.png` y `.pdf` | Los cuatro espectros y una tabla con las métricas calculadas por el S3. |
| `muestras.csv` | Índice, tiempo, limpia, mezcla, FIR, FFT y bandera de referencia válida. |
| `espectros.csv` | Frecuencia y densidad espectral en dB de cada señal, calculada en el S3. |
| `metricas.csv` | MSE, SNR de entrada/salida, mejora, energía útil y recortes PWM reportados por el S3. |
| `metadatos.json` | Parámetros, número de muestras evaluadas, cobertura de referencia, motivo de finalización y variación de contadores de recepción durante la toma. |
| `captura.s3bin` | Descarga original con CRC, para regenerar las figuras sin volver a capturar. |

Las gráficas temporales marcan en ámbar los intervalos sin referencia. La línea limpia queda interrumpida en esos intervalos. Todas las amplitudes se expresan en códigos del ADC. El S3 compensa las 40 muestras de retardo del FIR para comparar el mismo instante en las cuatro pistas.

El espectro es una **densidad espectral de potencia de Welch**, con ventana Hann periódica de 1024 muestras, salto de 512 y normalización por la energía de la ventana y la frecuencia de muestreo. El S3 calcula también la conversión a dB. La separación entre puntos de frecuencia es 15,625 Hz. El eje vertical está en dB respecto a 1 código ADC²/Hz y el eje horizontal llega hasta 8000 Hz. La amplitud de las señales se conserva para que la comparación revele las pérdidas introducidas por los filtros.

Si existen ventanas completas con referencia, los cuatro espectros utilizan exactamente esas mismas ventanas. Si falta referencia completa, se muestran los espectros de mezcla, FIR y FFT disponibles y se indica la ausencia del espectro limpio. Una toma menor que 1024 muestras permite mostrar el tiempo y las métricas disponibles, pero produce una figura con el aviso de espectro insuficiente.

MSE y SNR incluyen todas las muestras individuales con referencia válida. La energía útil exige además contexto válido para filtrar la referencia. Por eso sus cantidades de muestras pueden diferir de las usadas en Welch. Cada figura indica la cobertura que le corresponde.

## 5. Cambiar el detalle de una figura guardada

Podés elegir otro intervalo temporal a partir del archivo recibido. El siguiente ejemplo dibuja un detalle de 50 ms que comienza en 100 ms. Reemplazá la ruta por la carpeta real de tu toma.

```powershell
python capturar_graficas.python --archivo "resultados\P3_rep1_FECHA\captura.s3bin" --prueba P3 --repeticion 1 --inicio-ms 100 --detalle-ms 50
```

Se genera una carpeta nueva. El programa reutiliza los espectros y las métricas que ya calculó el S3. Para la primera vista automática elige un intervalo continuo con referencia cuando hay uno suficientemente largo.

## 6. Descargar una captura hecha desde Arduino IDE

El método recomendado es abrir Python antes de grabar. Si ya tenés un clip en estado LISTA, podés intentar descargarlo directamente.

```powershell
python capturar_graficas.python --puerto COM3 --prueba P3 --repeticion 1 --descargar-existente
```

Si al cambiar de programa la placa se reinicia, el clip desaparece de RAM y Python informa que falta una captura lista. Volvé a ejecutar sin `--descargar-existente` y grabá desde esa sesión.

## 7. Operación del S3 y validación

El comando `r` arma la captura con referencia. Los comandos `g` (captura libre), `s`, `p`, `e` e `i` siguen disponibles. El comando nuevo `x` produce una descarga binaria y está pensado para el programa de Python. `q` devuelve un estado breve que Python utiliza para detectar el arranque y el final de cada grabación. Durante la descarga el S3 congela el clip y pausa los filtros. El núcleo 0 continúa leyendo y validando las tramas UART. Al terminar, los filtros reinician su estado con datos nuevos. Los cálculos espectrales para las gráficas se realizan después de grabar, en el núcleo 1.

La descarga lleva CRC-32 sobre los metadatos y las muestras/espectros. Python rechaza los paquetes alterados o incompletos. Una transferencia válida certifica que llegaron los bytes enviados. Para evaluar la adquisición, revisá además los contadores guardados de CRC UART, pérdidas, reinicios y descartes de cola, así como el motivo de cierre de la toma. Una captura terminada por un corte conserva el tramo continuo previo al corte y debe identificarse como tal en el análisis.

El firmware se compiló para ESP32-S3 con Arduino-ESP32 3.3.2 y CDC desactivado. Se validó el cálculo de Welch en C++ contra un cálculo independiente durante el desarrollo, incluyendo referencia completa, parcial, ausente, silencio y captura corta. Se comprobaron la lectura del formato binario, el rechazo de CRC incorrecto y la generación de PNG/PDF. Los datos sintéticos de esas comprobaciones quedan fuera de la entrega. La espera, el cierre al perder referencia y el menú Python se comprobaron con entradas controladas, sin una placa física conectada. La validación pendiente es ejecutar la descarga con tu S3 conectado y revisar las gráficas de una captura real de P3.

Documentación de las interfaces utilizadas.

- [Opciones USB y UART de Arduino-ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/guides/tools_menu.html).
- [Apertura de puertos y control DTR/RTS en pySerial](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
