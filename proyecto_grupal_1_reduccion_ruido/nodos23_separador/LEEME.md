# ESP32-S3 · nodos 2 y 3
El S3 recibe la mezcla de un solo micrófono desde el nodo 1. Con **g** guarda un fragmento filtrado por los dos métodos. Con **p** envía las dos pistas al selector y al PAM8403 desde el mismo instante. Durante la escucha el clip queda bloqueado. La UART puede seguir recibiendo el sonido del parlante sin incorporarlo a la grabación.

## Cargar y escuchar la primera prueba
1. Descomprimí el ZIP y abrí **nodos23/nodos23.ino** con todos los archivos de la carpeta juntos. En Arduino IDE elegí **ESP32S3 Dev Module** y el paquete **esp32 by Espressif Systems 3.3.2**. Instalá **Adafruit SSD1306** con sus dependencias **Adafruit GFX Library** y **Adafruit BusIO**. Si usás el puerto USB nativo, activá **USB CDC On Boot**. El sketch funciona por consola aunque la OLED esté desconectada.
2. Conservá el montaje de la prueba de cableado de la tabla. Empezá con el volumen del PAM de escucha al mínimo. Abrí solo el monitor del S3 a **115200**. En el emisor seleccioná **p 1** y **comp mezcla**. Esperá a que el diagnóstico se estabilice (dos actualizaciones, unos dos segundos).
3. Enviá **e** al S3. Ahí también verás la secuencia, el estado y si viene referencia. Verificá que crece el contador de tramas válidas y que CRC, pérdidas y descartes de cola se mantienen. Enviá **g**. La OLED muestra **GRABANDO** y el PAM de escucha queda en silencio.
4. Esperá **LISTA** o enviá **s** para terminar antes. Poné el emisor en silencio con **0** para escuchar solo el PAM de salida. En el S3 enviá **p**, seleccioná A y subí lentamente el volumen. Cuando termine, pasá a B y enviá **p** otra vez. Cada reproducción empieza en la primera muestra. Podés mover el selector durante la escucha para conmutar instantáneamente.
5. Enviá **e** para ver las métricas de ese clip. Para otra toma, reactivá el emisor en la prueba y componente deseados, esperá a que el diagnóstico se actualice y enviá **g** de nuevo.

| Conexión | Montaje |
|---|---|
| UART | TX **GPIO17 del nodo 1** a RX **GPIO16 del S3**, GND común. UART1 a 921600, 8N1. GPIO15 queda configurado como TX del S3 y puede quedar libre. |
| Salida A | **GPIO17 del S3** → filtro RC A existente → lateral A del selector. |
| Salida B | **GPIO18 del S3** → filtro RC B existente → lateral B del selector. |
| PAM8403 | Común del selector → acoplamiento y atenuador existentes → entrada PAM. Parlante entre L+ y L− del mismo canal. |
| Selector y OLED | Segundo polo a GPIO7 con pull-up interno. LOW indica A por defecto. OLED SSD1306 128×64 en SDA=8, SCL=9, 3,3 V, dirección 0x3C o 0x3D. |

| Comando del S3 | Acción |
|---|---|
| g | Empieza una captura nueva y reemplaza la anterior. Durante reproducción o grabación, primero enviá s. |
| s | Termina la grabación y conserva lo acumulado, o detiene la escucha. |
| p | En estado LISTA, reproduce una vez el mismo clip por A y B simultáneamente. |
| e | Imprime duración, estado, contadores, métricas y tiempo de cálculo más reciente. |
| i | Invierte la etiqueta A/B de la pantalla si el segundo polo del selector quedó invertido. |
| ? | Muestra la ayuda. |

## Qué queda guardado
En RAM interna queda un par de muestras PCM int16 por instante, en códigos del ADC. Las pistas consumen juntas 64 000 bytes/s. Al arrancar se reserva el mayor clip posible dejando 32 KiB de RAM libre como margen, con un máximo de 4 s. La OLED y la consola indican **duración grabada / capacidad real**. El clip se pierde al reiniciar o iniciar otra captura. La grabación termina automáticamente al llenarse, con resolución de 512 muestras (32 ms). Un corte de secuencia, un desborde o la ausencia de tramas durante un segundo cierra la toma en el último tramo continuo disponible.

## Rutas y sincronización
- **Núcleo 0.** Lee UART1 en trozos de hasta 512 bytes con búfer de recepción de 16 KiB. Verifica delimitador, versión 3, cabecera de 92 bytes, longitud y CRC-32 IEEE. Acepta tramas de 1 a 2048 muestras, con o sin referencia. Agrupa la entrada en saltos internos de 512. Mantiene el estado del FIR entre tramas y lo reinicia si la adquisición se interrumpe.
- **Nodo 2.** FIR Kaiser simétrico con los 81 coeficientes de resultados/fir_diseno.json del repositorio. Paso hasta 1500 Hz, inicio del rechazo a 2300 Hz, corte de diseño a 1900 Hz. A 16 kHz su retardo lineal es de 40 muestras (2,5 ms). Para comparar y grabar, el firmware alinea la salida del FIR con la referencia y la salida espectral.
- **Núcleo 1.** Recibe por cola la mezcla original, la referencia opcional y la salida del FIR. Usa la mezcla para la FFT. Reproduce el método espectral del repositorio con Hann periódica de análisis y síntesis, FFT/IFFT de 1024, salto de 512 y reconstrucción por suma solapada normalizada. La máscara usa mediana espectral de 31 bins, suavizado 0,8, sustracción con alfa 1,5 y piso 0,05. Aplica una envolvente de banda cuya transición predeterminada es 1500–2300 Hz. Si el diagnóstico trae confianza alta y un fin de banda útil válido, ajusta esa transición. Las líneas de diagnóstico sirven para interpretar la prueba. Este método estima su máscara a partir de la mezcla y el fin de banda, tal como en la simulación.
- **Salida.** Los dos PWM se actualizan a 16 kHz con reloj de 2 MHz y alarma cada 125 cuentas. La portadora es 156250 Hz a 9 bits. Ambas rutas usan la misma ganancia digital (centro 256 y variación de un paso PWM por cada cuatro códigos ADC); así se conserva la diferencia de nivel entre métodos. Un contador por pista avisa si la conversión al PWM recortaría picos.
- **Alcance de los filtros.** La banda fija del FIR favorece P1 y P2, pero también atenúa partes útiles de una canción o de un chirp por encima de su banda. En P3, P4 y P5 conviene comparar grabaciones y métricas antes de atribuir una mejora al filtro.

## Evaluar con referencia
En tus trazas, **0x00** permite grabar y escuchar. Para medir MSE, SNR y energía útil, seleccioná primero la prueba en el emisor, poné **comp limpia** y ejecutá **ref capturar 8** en el nodo 1. Mantené fijo el montaje y esperá a que indique **lista**. Volvé a **comp mezcla**, esperá el diagnóstico y grabá en el S3. Repetí la referencia por cada prueba nueva. Dejá abierto el monitor del nodo 1 durante esta secuencia para evitar un reinicio por apertura del puerto.

El informe usa las mismas muestras válidas para ambos métodos y omite referencias −32768. MSE está en códigos ADC al cuadrado. SNR de entrada y salida compara energía de referencia con energía de error. La energía útil compara la energía de la referencia procesada por el mismo FIR o la misma máscara congelada de la mezcla con la energía original, solo en ventanas con contexto válido. Por eso el contador de energía puede ser menor. **N/D** indica que faltan datos o que la razón está indefinida. Las métricas se congelan con el clip y corresponden a la salida digital antes del PWM, RC y PAM.

En tramas de 1024 muestras, el presupuesto de entrada es 64 ms; procesar un salto de 512 consume parte de 32 ms. Los tiempos impresos son de cálculo en el S3. El dato de núcleo 0 incluye desempaquetado y FIR; el de núcleo 1 incluye FFT/WOLA y, cuando corresponde, la segunda pasada de referencia. La latencia física además incluye adquisición, UART y espera por bloques. Para la evidencia experimental quedan las medidas del montaje, entre ellas la atenuación de la interferencia y la respuesta analógica. En cada repetición anotá contadores antes y después; si crecen durante la toma, verificá el enlace y repetila.

## Verificación del código entregado
Se compiló para **esp32:esp32:esp32s3** con Arduino-ESP32 3.3.2 y USB CDC al arranque. La compilación usó 381851 bytes de flash y 105664 bytes de variables globales; el búfer de grabación se asigna después, en ejecución. En PC se compararon el FIR y la reconstrucción espectral con los cálculos de referencia sobre fragmentos de seis registros del repositorio. Antes del redondeo PCM, el error absoluto máximo observado fue menor de 0,001 códigos ADC. También se ensayaron tramas con/sin referencia, CRC incorrecto y resincronización tras truncar una trama. El sonido en el PAM, la duración de RAM disponible y los tiempos efectivos bajo carga requieren prueba en la placa.
