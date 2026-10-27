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

## Uso de IA

Se utilizó ChatGPT para planificación, interpretación y borrador del informe. Se suministraron enunciados, notebook docente y apuntes del curso. Se verificaron ecuaciones, SNR, DFT/FFT, simetría, reconstrucción, FIR frente a biblioteca, métricas analíticas y figuras.
