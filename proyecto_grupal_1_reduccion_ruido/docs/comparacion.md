# Comparación automática y criterios de interpretación

Ejecute `src/comparacion.py` con Run Python File en VS Code. Se regeneran
los casos y las salidas usando los JSON actuales; no se reutilizan métricas
antiguas. Los módulos `metricas.py` y `comparacion.py` también son importables.

## Intervalo y alineación

Con L=96000, N=1024 y FIR de orden 80/retardo D=40, la referencia común
es s[1024:94936]: 93912 muestras. Entrada y salida espectral usan exactamente
ese intervalo. El FIR se evalúa en y[1064:94976], compensando solo su retardo
de grupo conocido. No se optimiza el desplazamiento para mejorar la SNR y
no se ajustan amplitudes ni fases. Se excluyen bordes para todos los métodos.

Los índices se guardan en el CSV y los arrays alineados en
`resultados/comparacion/caso_X/salidas_alineadas.npz`. Si se cambia el diseño,
el intervalo se recalcula. Esta alineación compara calidad; la latencia
física del sistema continúa siendo un resultado pendiente del hardware.

## Métricas

Se usan las ecuaciones de la Tarea 1, apartado 2.5:

$$\mathrm{MSE}=\frac{1}{L_v}\sum_n(s[n]-\widehat s[n])^2,$$

$$\mathrm{SNR}=10\log_{10}\frac{\sum_n s[n]^2}{\sum_n(s[n]-\widehat s[n])^2},$$

$$\Delta\mathrm{SNR}=\mathrm{SNR}_{salida}-\mathrm{SNR}_{entrada}.$$

L_v es la longitud del intervalo válido común, no la grabación completa.
El error incluye ruido residual y distorsión de la señal útil.
La SNR configurada de 2 dB se verifica sobre el registro completo. En el
intervalo recortado puede variar ligeramente (aproximadamente 2.01–2.02 dB
en estos casos), por excluir el fade y usar otra realización parcial del
ruido. La mejora se calcula contra la entrada de ese MISMO intervalo.

Energía útil conservada: energía del componente limpio procesado dividida
por la energía limpia de referencia. En el espectral se congelan las máscaras
aprendidas desde la mezcla y se aplican después a cada componente para
auditar su contribución. No se aprende desde las referencias. Se comprueba
que las dos contribuciones suman la salida real. En FIR se aprovecha su linealidad.

La atenuación del ruido total es 10 log10(E_ruido/E_ruido_residual).
Para la componente dominante se mide amplitud mediante proyección sobre
seno/coseno y se usa 20 log10(A_entrada/A_salida). En ruido tonal se utiliza
su frecuencia exacta conocida por el evaluador. En ruido de banda se busca
el bin máximo del ruido aislado en el intervalo válido. Esa frecuencia es
una característica de esa realización aleatoria, no de toda la banda.
La frecuencia se determina exclusivamente para evaluar, no para configurar
la reducción espectral.

## Tiempo de ejecución y memoria

Se realizan 7 repeticiones después de calentamiento usando un prefijo de
24 bloques, con el estado reiniciado en cada repetición. Se divide el tiempo
total de procesamiento por el número de bloques FIR o marcos espectrales.
Se reporta mediana y percentil 95 de esos tiempos amortizados. No es el
percentil 95 de latencias individuales de bloques.

El costo temporal incluye asignaciones del wrapper offline, pero no diseño,
gráficas, referencias de evaluación, archivos ni comunicación. FIR trabaja
en bucle Python; FFT/IFFT usa bibliotecas optimizadas. El resultado NO permite
afirmar que FFT será intrínsecamente más rápida en firmware.

FIR procesa 1024 muestras nuevas por bloque; el espectral incorpora 512 por
marco de 1024. Se guarda también el costo amortizado por muestra y el período
de actualización, para no confundir unidades de trabajo distintas.

La RAM base propuesta con float32/complex64 es 8836 bytes para FIR (644
de coeficientes/estado más 8192 de buffers) y 36896 para el espectral. Es
un presupuesto de diseño: no una medición de Python o del firmware. Se
excluyen scratch de FFT, pila, librerías y comunicación. Para la entrada sin
filtrar se fija costo adicional de filtrado cero; no se afirma que capturar
y reproducir una señal requiera cero memoria o tiempo.

El entorno y las versiones de Python/NumPy/SciPy se registran en JSON.
Las señales y las métricas son reproducibles; los tiempos varían por máquina
y carga del sistema.

## Objetivos de calidad propuestos

En `metadatos/comparacion.json` se declaran antes de ejecutar la comparación final:

- Casos separados: mejora mínima de 10 dB y energía útil conservada mínima 95%.
- Caso superpuesto: mejora mínima de 2 dB y energía útil conservada mínima 90%.
- En ambos: ninguna muestra de salida fuera del rango digital [-1,1].

Estos son objetivos propuestos para este banco sintético; NO son umbrales
impuestos por el profesor ni un criterio de aprobación del proyecto entero.
El FIR puede fallar en el caso 3 y se reporta explícitamente. No se deben
relajar los límites para ocultar ese fallo. Energía conservada es solo una
condición: una señal puede conservar energía y estar distorsionada; por eso
se reportan también MSE, SNR y distorsión del componente útil.

## Interpretación

Con las configuraciones iniciales, el FIR conserva mejor los multitonos en
los casos separados y su rechazo reduce mucho el ruido. El espectral mejora
más la superposición parcial, con cierta pérdida de información útil. Ambos
métodos pueden fallar cuando sus hipótesis no se cumplen: ruido dentro de
la banda de paso para el FIR; señales útiles de banda ancha o tonos débiles
para el estimador espectral basado en mediana.

La selección final debe considerar además recursos, latencia y resultados
medidos en hardware. Aún faltan placa concreta, comunicación entre nodos,
licencias/bibliotecas, informe PDF y empaque de entrega.

## Fuentes y verificación

Las métricas siguen la Tarea 1 (apartado 2.5); energía y representación
frecuencial se apoyan en los apuntes S6L2, S7L1 y S7L2 del curso. La
proyección sobre seno/coseno y la compensación del retardo son procedimientos
de evaluación explícitos de esta implementación.

Pruebas nuevas: reducción conocida de ruido, energía útil distinta de
energía total, alineación de un retardo conocido, frecuencia/amplitud de
un tono conocido y rechazo de longitudes incompatibles. Mantener también
las pruebas de los módulos previos.

Asistencia de IA: implementación y explicación. Verificación mediante
ecuaciones, casos analíticos, pruebas automáticas, reproducibilidad de señales
y revisión de figuras. Adaptar esta declaración al trabajo real del grupo.
