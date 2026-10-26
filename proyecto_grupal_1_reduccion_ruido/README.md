# Tarea 1 — Caracterización y reducción de ruido

Curso CE1110, Análisis de Señales Mixtas. Entrega: 14 de octubre de 2026.

- Repositorio: https://github.com/gabonm14/gnunez_asm_2026_s2
- Carpeta: `proyecto_grupal_1_reduccion_ruido`
- Tag requerido: `tarea1_prototipo` (crear y subir después de integrar y verificar).
- Integrantes: Gabriel Bolaños Barboza y Gabriel Núñez Morales
## Instalación y VS Code

Desde esta carpeta, instale `requirements.txt` en un entorno Python 3.12. En Windows puede ubicar el entorno fuera del repositorio para evitar rutas largas; se usó `C:\Users\XPC\venvs\asm`. En VS Code seleccione su `Scripts/python.exe` como intérprete y como kernel del notebook.

Abra `notebook.ipynb`, reinicie kernel y ejecute Run All. Se regeneran señales, figuras y tablas, incluyendo FIR, espectral y comparación final. No se necesita pandas.

Para regenerar todo con un solo botón ejecute `src/ejecutar_todo.py`. Después recompile el PDF.

Los scripts `src/generacion.py`, `src/analisis.py`, `src/filtros_temporales.py`, `src/filtrado_espectral.py`, `src/comparacion.py` y `src/actualizar_informe.py` funcionan con Run Python File in Terminal. Genere la comparación antes de actualizar las tablas del informe.

Equivalente por terminal desde esta carpeta:

```bash
python -m src.analisis
python -m src.filtros_temporales
python -m src.filtrado_espectral
python -m src.comparacion
python -m src.plan_frecuencias
python -m src.actualizar_informe
python -m unittest discover -s tests -v
```

## Resultados

Configuraciones y semillas en `metadatos/`; WAV y NPZ float64 en `pruebas/caso_X/`. Las referencias exactas para métricas son NPZ, ya que PCM16 cuantiza. `resultados/metricas.csv` es la comparación final de nueve filas sobre un intervalo común. Los tiempos se regeneran por máquina; no son resultados del firmware.

El informe PDF incluido contiene resultados del entorno de referencia indicado en `resultados/comparacion_metadatos.json`. Si quiere usar los tiempos de su computadora, ejecute comparación, actualice tablas y recompile. El resto de métricas debe coincidir salvo precisión numérica.

## Plan de frecuencias: separación mínima y latencia (proyecto)

Se regenera con `python -m src.plan_frecuencias`. Los requisitos están en `metadatos/plan_frecuencias.json` y los criterios de aceptación se toman de `metadatos/comparacion.json` (casos separados: mejora ≥ 10 dB y energía útil ≥ 95 %).

Salidas: `resultados/plan_frecuencias_candidatos.csv` (tabla de valores de N) y `resultados/figuras/plan_frecuencias_separacion.png` (figura del barrido). Los avisos se imprimen en pantalla.

Configuración actual: fs = 16 kHz y N = 1024, con Δf = fs/N = 15.625 Hz. Requisitos declarados:

- **d_min = 80 Hz:** separación mínima entre interferencia y tono útil (440, 880 o 1320 Hz) que el sistema debe resolver. Es la separación medida con N = 1024 (ver tabla).
- **L = 64 ms:** latencia máxima del buffer N/fs, sin contar procesamiento ni comunicación.

Ambos dependen de N y no se eligen por separado. Con Hann, un tono ocupa el lóbulo principal de ±2 bins, así que dos componentes solo se separan si están a más de 4Δf = 4·fs/N. La latencia del buffer es N/fs, de modo que d_min·L ≥ 4: mejorar la resolución cuesta latencia y memoria en la misma proporción.

Con estos requisitos, la parte analítica da N ≥ 1024 por resolución y N ≤ 1024 por latencia, así que solo N = 1024 los cumple.

### Método del barrido

Se usa un prototipo de máscara por detección de picos. No es el método final del nodo 3; sirve para dimensionar N.

- **Ventana y solapamiento:** Hann de análisis y síntesis, solapamiento 50 %.
- **Detección:** en cada marco se buscan picos con prominencia de 20 dB. Los picos a ≤ 1 bin de un tono útil conocido se respetan y el resto se anula en ±2 bins.
- **Señal de prueba:** los tres tonos más una interferencia tonal a ±d Hz de cada tono útil, con SNR de entrada de 2 dB.
- **Repeticiones:** tres semillas, que cambian la fase de la interferencia.
- **Evaluación:** con máscaras congeladas sobre la señal útil y la interferencia por separado. "d medido" es la menor separación desde la cual todas las combinaciones de tono, lado y semilla cumplen los criterios.

### Resultados según N

| N | Δf (Hz) | 4Δf teórico (Hz) | d medido (Hz) | Latencia N/fs (ms) | Readaptación (ms) | Memoria base (bytes) |
|---|---:|---:|---:|---:|---:|---:|
| 256 | 62.5 | 250 | no cumple hasta 300 | 16 | 11.3 | 9 248 |
| 512 | 31.25 | 125 | 125 | 32 | 28.9 | 18 464 |
| **1024** | **15.625** | **62.5** | **80** | **64** | **43.0** | **36 896** |
| 2048 | 7.8125 | 31.25 | 45 | 128 | 74.4 | 73 760 |

Cómo leer las columnas:

- **Readaptación:** cuánto tiempo el error supera −30 dB cuando la interferencia salta de 2500 a 3100 Hz. Es lo que tardaría el sistema en reaccionar si el ruido cambia durante la defensa.
- **Memoria base:** misma fórmula que `filtrado_espectral.py`. No incluye biblioteca FFT, pila ni comunicación.
- **Con N = 256:** la máscara de ±125 Hz alcanza a los tonos vecinos, así que el método no es utilizable con estos tonos.

### Interpretación

- **El 4Δf teórico es una cota necesaria, no suficiente.** Con N = 1024 el peor caso es una interferencia en 380 Hz (440 − 60 Hz) con amplitud parecida a la del tono. A 3.84 bins los lóbulos de Hann se tocan, el valle entre ambos picos no alcanza la prominencia de 20 dB y el detector no ve la interferencia. Solo atenúa ≈ 3 dB.
- **Por debajo de la separación medida hay dos fallos posibles.** O la interferencia se confunde con el tono útil y no se elimina (atenuación de 0 dB), o se elimina junto con el tono (con 880 Hz la energía útil cae a ≈ 78 %). Este es el compromiso entre eliminación de ruido y distorsión que se evalúa en P5.
- **Interferencias en bin frente a fuera de bin.** Con 2500 Hz, que cae exacto en un bin para todos los N, el residuo es de −111 a −162 dB respecto a la potencia útil. Con 3100 Hz, que cae entre bins, sube a −41 a −49 dB. El caso 1 actual usa 2500 Hz y por eso sobreestima el desempeño. Las pruebas deben incluir interferencias fuera de bin.

### Decisión

Se usa N = 1024 con d_min = 80 Hz y 64 ms de latencia de buffer.

- **Por qué no 2048:** bajaría d_min a 45 Hz, pero duplicaría la latencia (128 ms) y la memoria.
- **Por qué no 512:** subiría d_min a 125 Hz.
- **Mejora posible:** si el detector final del nodo 3 se acerca a la cota teórica de 62.5 Hz, se vuelve a medir y se actualiza d_min.

### Limitaciones

- **Cobertura:** solo hay interferencia tonal, con una amplitud fija (SNR de 2 dB). Falta variar la amplitud relativa.
- **Parámetros del detector:** la prominencia, la tolerancia y los ±2 bins son del prototipo. Otro detector dará otra separación medida.
- **Prueba de transitorios:** una ráfaga con inicio abrupto no mostró diferencias entre valores de N, porque la máscara no toca su banda. No sirve como evidencia para P4.
- **Pendiente en el ESP32:** la memoria y el tiempo de cálculo por bloque deben medirse en hardware.

## Uso de IA

Se utilizó ChatGPT para planificación, interpretación y borrador del informe. Se suministraron enunciados, notebook docente y apuntes del curso. Se verificaron ecuaciones, SNR, DFT/FFT, simetría, reconstrucción, FIR frente a biblioteca, métricas analíticas y figuras.
