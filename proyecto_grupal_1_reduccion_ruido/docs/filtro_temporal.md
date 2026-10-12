# Filtro temporal FIR: decisiones y explicación

Este módulo es la referencia causal de software para el futuro nodo temporal.
El filtro se diseñó para ruido separado de la banda útil (casos 1 y 2), y se
aplicó también al caso de superposición (caso 3). La implementación recibe
solamente la entrada contaminada, no la referencia limpia.

## Especificaciones fijadas antes de evaluar las salidas

- Muestreo: 16000 Hz.
- Banda de paso: 0 a 1500 Hz; incluye los tonos 440, 880 y 1320 Hz.
- Transición: 1500 a 2300 Hz.
- Banda de rechazo: 2300 Hz a Nyquist (8000 Hz); incluye la interferencia a 2500 Hz.
- Rizado máximo pico a pico: 0.1 dB; se verifica también la desviación respecto de 0 dB.
- Atenuación mínima de rechazo: 60 dB.
- Kaiser: objetivo 65 dB, con 5 dB de margen sobre el rechazo deseado.

`kaiserord` estima longitud y beta. `firwin` calcula coeficientes. Se verifica
el diseño en una malla densa con `freqz` y se aumenta la longitud si no cumple.
No se afirma que este orden sea el mínimo entre todos los métodos de diseño.
El corte de `firwin`, 1900 Hz, está en el centro de la transición y representa
aproximadamente media amplitud (-6 dB), no el borde de la banda de paso.

## Ecuación, H(z) y estabilidad

$$y[n]=\sum_{k=0}^{80}b_k x[n-k].$$

No aparecen salidas anteriores en el lado derecho: no hay realimentación.
Los 81 coeficientes completos se guardan en `resultados/coeficientes_fir.csv`
y en `resultados/fir_diseno.json`, donde `a=[1]`.

$$H(z)=\sum_{k=0}^{80}b_kz^{-k}
=\frac{b_0z^{80}+b_1z^{79}+\cdots+b_{80}}{z^{80}}.$$

En esta representación, los polos están en z=0, con multiplicidad 80; los
ceros son las raíces del numerador. Para esta secuencia causal finita, la ROC
es |z|>0 e incluye el círculo unitario. Es BIBO estable porque
$\sum_k|b_k|$ es finita. Un cero fuera del círculo unitario NO implica
inestabilidad: esa condición se evalúa con los polos y la ROC.

## Fase, retardo y procesamiento por bloques

Los coeficientes son simétricos, por lo que el FIR tipo I tiene fase lineal
(en los intervalos entre ceros) y retardo de grupo de 40 muestras:

$$D=\frac{81-1}{2}=40,\qquad D/f_s=2.5\text{ ms}.$$

El programa implementa la suma de productos con 80 muestras de estado.
Conserva ese estado entre bloques: el resultado no depende del tamaño de
bloque elegido. Reiniciar el estado en cada bloque sería incorrecto.
El retardo de grupo no incluye tiempo de adquisición de bloques, ejecución,
comunicación ni conversión ADC/DAC.

## Verificación y métricas

La salida propia se compara con `scipy.signal.lfilter` con estados iniciales
cero y tolerancias atol=1e-12, rtol=1e-10. Las pruebas incluyen impulso,
señal aleatoria con bloques de longitud 1, 17, 1024 y 4099, y retardo de un tono.

Las señales exportadas son causales y conservan el retardo. Solo para evaluar
se compara `s[80:L-40]` con `y[120:L]`: se compensa el retardo y se excluyen
bordes/transitorios. El CSV registra los índices, SNR alineada y SNR sin
alinear. Compensar el retardo para comparar no significa eliminarlo del sistema.
Las métricas finales de ambos métodos deben usar un intervalo común.

Para medir energía útil conservada se filtra también la referencia limpia,
solo en evaluación. La energía del componente limpio filtrado se compara con
la energía de la referencia en el mismo intervalo; no se confunde con la
energía total de la salida contaminada. `atenuacion_ruido_total_db` mide el
ruido aislado completo; la atenuación específica de la interferencia dominante
se añadirá en la comparación final.

## Cuantización, memoria y saturación

Se compara la respuesta usando coeficientes float64, coeficientes redondeados
a float32 y coeficientes Q1.15. Esta última prueba NO emula operaciones enteras,
redondeo de productos, acumulación ni saturación. Ese análisis sigue pendiente
para la placa concreta. Un FIR sigue siendo estable con coeficientes finitos
cuantizados, aunque su respuesta puede cambiar.

En forma directa se requieren 81 multiplicaciones y 80 sumas por muestra.
Coeficientes y estado float32: 644 bytes; buffers de entrada/salida de 1024
muestras float32: 8192 bytes adicionales. No se incluyen FFT, pila,
comunicación, bibliotecas o el intérprete Python.

La cota $|y[n]|\leq\max|x[n]|\sum_k|b_k|$ permite evaluar riesgo de desborde.
El programa guarda esa cota y el pico observado en cada caso. No renormaliza
la salida del filtro. El WAV PCM16 puede recortar amplitudes fuera de [-1,1];
el número de muestras fuera de rango se registra, y las métricas usan float64.

## Fuentes y trazabilidad

Se priorizan los apuntes del curso S7L2, *Caracterización en tiempo y frecuencia*,
para fase y retardo de grupo; S6L2 y S7L1 para respuesta en frecuencia y señales.
La ecuación FIR, H(z), polos, ROC y las verificaciones son el desarrollo
matemático de esta implementación, acorde con el apartado 2.3 de la Tarea 1.
No se atribuye a los apuntes de Laplace una definición de la transformada Z.

Para el uso específico de las funciones de diseño, se consultó documentación primaria:

- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.kaiserord.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.firwin.html

Asistencia de IA: propuesta de estructura, código de referencia y explicación.
Verificación: especificaciones medidas, comparación contra biblioteca,
pruebas automáticas y revisión de gráficas. El grupo debe revisar y adaptar
esta declaración al uso real antes de la entrega.
