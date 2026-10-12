# Reducción espectral: método, supuestos y verificación

## Entrada y configuración

Se procesan marcos de N=1024 muestras, con salto H=512, fs=16000 Hz.
Se usa Hann periódica tanto para análisis como para síntesis. La separación
entre bins es 15.625 Hz; cada marco cubre 64 ms y se actualiza cada 32 ms.
Estos tiempos no son medidas de ejecución ni de latencia total del hardware.

El método conoce la banda útil nominal (hasta 1500 Hz), pero no recibe la
frecuencia de la interferencia ni la señal limpia. Es un banco de señales
multitono: no se afirma que estas hipótesis sean válidas para cualquier audio.
Todos los parámetros están en `metadatos/filtro_espectral.json`.

## Algoritmo por marco

1. Aplicar ventana Hann al marco de entrada.
2. Calcular `rfft`: N/2+1 coeficientes complejos.
3. Calcular P[k]=|X[k]|². No es una PSD calibrada ni potencia temporal.
4. Estimar el fondo de ruido con una mediana local de 31 bins.
5. Suavizar esa estimación entre marcos con beta=0.8.
6. Obtener una ganancia real adaptativa y multiplicar el espectro complejo.
7. Reconstruir con `irfft`, volver a aplicar Hann y sumar los marcos solapados.
8. Dividir por la suma de cuadrados de las ventanas que cubren cada muestra.

La estimación es:

$$\widehat P_{r,m}[k]=\beta\widehat P_{r,m-1}[k]
 +(1-\beta)\operatorname{mediana}_{j\in V_k}P_m[j].$$

En el primer marco se inicializa directamente con la mediana local.
La ganancia de reducción es:

$$G_m[k]=B[k]\sqrt{\max\left(1-\alpha
 \frac{\widehat P_{r,m}[k]}{P_m[k]+\epsilon},g_{\min}^2\right)}.$$

Aquí alpha=1.5, g_min=0.05 y epsilon es un piso numérico relativo.
B[k] conserva la banda hasta 1500 Hz, aplica una transición cosenoidal hasta
2300 Hz y deja ganancia 0.001 (-60 dB) por encima de 2300 Hz.
El parámetro alpha es ajustable y el ruido estimado cambia por marco.
No se anula un bin de posición conocida.

La mediana local y este suavizado son una heurística propia del prototipo,
no un estimador óptimo ni una separación demostrablemente exacta. Suponen
que los tonos útiles ocupan menos bins que el vecindario y destacan sobre
el ruido. Pueden degradar tonos débiles, transitorios o audio útil de banda
ancha. Al variar alpha se expone esta limitación, no se la oculta.

## Simetría conjugada y fase

Se aplica Y[k]=G[k]X[k], con ganancias reales y no negativas. `irfft`
reconstruye las frecuencias negativas conjugadas de las positivas. DC y
Nyquist se mantienen reales. La fase de cada coeficiente no nulo se conserva,
aunque la fase del espectro global reconstruido no tiene por qué ser idéntica
al original cuando las ganancias cambian en el tiempo.

Se verifica además una IFFT compleja con el espectro completo construido
explícitamente, para no confundir salida real de `irfft` con una prueba por sí sola.

## Reconstrucción WOLA

Con ventana de análisis y síntesis w, el registro se reconstruye mediante:

$$\widehat x[n]=\frac{\sum_m w[n-mH]\widetilde x_m[n-mH]}
 {\sum_m w^2[n-mH]}.$$

El denominador debe ser positivo (condición NOLA). Se verifica esa condición
y se añade padding de bordes para no perder la primera/última muestra.
Después se recorta a la longitud original. El padding no aumenta la resolución
de la FFT: cada marco sigue teniendo exactamente N muestras.

Con G=1, cada IFFT devuelve el marco ventaneado; la segunda ventana produce
w², que queda compensada por el denominador. Se prueban longitudes 1, 257,
1024 y 11111 para cubrir extremos y bloques finales incompletos.

## Evaluación sin usar referencias en el algoritmo

La máscara se estima una única vez a partir de la mezcla. Para auditar la
energía útil y el ruido residual, se aplica esa MISMA secuencia de máscaras
a la referencia limpia y al ruido aislado. No se aprende una máscara nueva
desde cada referencia. Con máscaras congeladas, el operador es lineal y se
verifica salida_mezcla = salida_limpia + salida_ruido, dentro de tolerancia.

La energía útil conservada se calcula con la salida del componente limpio,
no con la energía total de la salida. La distorsión útil es su MSE respecto
a la referencia limpia. La atenuación de ruido se calcula con el componente
de ruido residual. MSE y SNR generales incluyen ambos errores.

Se excluyen N muestras por borde y se guardan los índices de evaluación.
La comparación final con FIR deberá usar el mismo intervalo válido para ambos.

## Prueba de reducción agresiva

En el caso 3 se comparan alpha=0.5, 1.5, 4 y 12, valores prefijados en JSON.
Se reportan atenuación del ruido, energía útil conservada y distorsión del
componente útil. Una mayor atenuación no demuestra por sí sola mejor calidad:
puede aumentar el MSE de señal útil. Esto se muestra en
`espectral_compromiso.csv` y `espectral_compromiso.png`.

## Conexión futura con el sistema embebido

`EstimadorEspectral` conserva la estimación de ruido entre marcos y usa solo
el marco actual y su estado anterior. La envoltura `reducir_espectral` es
una referencia offline: conserva arrays completos y máscaras históricas para
auditoría. No es todavía firmware ni una API de adquisición en tiempo real.
La implementación embebida necesitará buffers circulares de entrada y WOLA,
control del estado, delimitación de bloques y medición de latencia física.

La salida guardada está alineada con el tiempo de referencia del archivo;
esto NO significa que se pueda emitir sin esperar muestras futuras. Se
requiere llenar marcos y completar contribuciones solapadas. Esa espera,
sumada a ejecución, comunicación y conversión, se medirá con el hardware.

La estimación base de memoria cuenta 5 buffers reales de N muestras
(entrada, ventana, marco sintetizado, acumulación WOLA y pesos), 4 buffers
reales de N/2+1 (potencia, mediana, ruido estimado y ganancia) y 2 buffers
complejos de N/2+1 (X,Y). Con float32/complex64 son 36896 bytes. No incluye
scratch de la FFT, pila ni comunicaciones. No es una medición de memoria de
Python; NumPy utiliza aquí float64/complex128. Las máscaras históricas se
guardan solo en esta referencia offline, no se necesitan todas en el hardware.

## Fuentes

Primero se usan los apuntes del curso S6L2 y S7L1 para transformadas,
multiplicación espectral y simetría conjugada, y S7L2 para magnitud/fase.
La fórmula de reconstrucción y la heurística se explican por sus ecuaciones
y se verifican mediante pruebas propias. Para detalles de las APIs y NOLA:

- https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html
- https://numpy.org/doc/stable/reference/generated/numpy.fft.irfft.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.check_NOLA.html

Asistencia de IA: estructura, algoritmo de referencia, código y explicación.
Verificación: pruebas automáticas de identidad, simetría, adaptación,
descomposición con máscaras congeladas y revisión de figuras. El grupo debe
revisar y adaptar esta declaración a su uso real antes de entregar.
