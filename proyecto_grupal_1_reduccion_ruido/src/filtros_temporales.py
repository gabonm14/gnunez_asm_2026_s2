"""FIR causal pasa bajas: diseño, implementación propia y validación.

Ejecutable con Run Python File en VS Code y con python -m src.filtros_temporales.
Diseño por ventana Kaiser (SciPy). El procesamiento propio conserva estado
entre bloques y aplica y[n] = sum_k b[k] x[n-k]; no usa convolución ni lfilter.
"""
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.signal import firwin, freqz, kaiserord, lfilter

if __package__ in (None, ''):
    from generacion import RAIZ, generar_todos, pcm16, snr_db
    from analisis import guardar_csv, guardar_figura, espectro_bloque
else:
    from .generacion import RAIZ, generar_todos, pcm16, snr_db
    from .analisis import guardar_csv, guardar_figura, espectro_bloque


def medir_respuesta(b, spec):
    """Verifica paso/rechazo con una malla densa; no incluye transición."""
    f, H = freqz(b, worN=65536, fs=spec['fs_hz'])
    paso_db = 20 * np.log10(np.maximum(abs(H[f <= spec['paso_hz']]), 1e-15))
    rechazo = float(-20 * np.log10(max(abs(H[f >= spec['rechazo_hz']]))))
    return {'rizado_pico_a_pico_db': float(np.ptp(paso_db)),
            'desviacion_paso_max_db': float(max(abs(paso_db))),
            'atenuacion_rechazo_min_db': rechazo}


def disenar_fir(spec):
    """Número de coeficientes estimado por Kaiser y verificado por freqz.

    El objetivo Kaiser es más estricto que los 60 dB exigidos por nuestro
    diseño, para dejar margen a la aproximación del orden. El orden NO se
    considera mínimo global. Longitud impar -> FIR tipo I y retardo entero.
    """
    fs = spec['fs_hz']
    if not 0 < spec['paso_hz'] < spec['rechazo_hz'] < fs / 2:
        raise ValueError('Debe cumplirse 0 < paso < rechazo < fs/2.')
    if spec['rizado_max_db'] <= 0 or spec['atenuacion_min_db'] <= 0:
        raise ValueError('Rizado y atenuación deben ser positivos.')
    # Error lineal de amplitud compatible con el rizado especificado.
    delta = (10 ** (spec['rizado_max_db'] / 20) - 1) / (10 ** (spec['rizado_max_db'] / 20) + 1)
    objetivo = max(spec['atenuacion_min_db'], -20 * np.log10(delta)) + spec['margen_kaiser_db']
    longitud, beta = kaiserord(objetivo, (spec['rechazo_hz'] - spec['paso_hz']) / (fs / 2))
    longitud = max(3, int(longitud))
    if longitud % 2 == 0:
        longitud += 1
    corte = (spec['paso_hz'] + spec['rechazo_hz']) / 2
    for _ in range(100):
        b = firwin(longitud, corte, window=('kaiser', beta), fs=fs, scale=True)
        medida = medir_respuesta(b, spec)
        if (medida['rizado_pico_a_pico_db'] <= spec['rizado_max_db'] and
                medida['desviacion_paso_max_db'] <= spec['rizado_max_db'] and
                medida['atenuacion_rechazo_min_db'] >= spec['atenuacion_min_db']):
            return b, {**medida, 'num_coeficientes': longitud, 'orden': longitud - 1,
                       'beta_kaiser': float(beta), 'objetivo_kaiser_db': float(objetivo),
                       'corte_firwin_hz': corte, 'retardo_muestras': (longitud - 1) // 2,
                       'retardo_ms': 1000 * (longitud - 1) / (2 * fs)}
        longitud += 2
    raise RuntimeError('No se obtuvo un diseño que cumpla las especificaciones.')


class FIRCausal:
    """Forma directa con M muestras anteriores, inicialmente cero.

    El mismo objeto debe procesar todos los bloques consecutivos.
    Reiniciarlo en cada bloque crearía transitorios artificiales.
    """
    def __init__(self, coeficientes, dtype=np.float64):
        self.b = np.asarray(coeficientes, dtype=dtype).copy()
        if self.b.ndim != 1 or not len(self.b) or not np.all(np.isfinite(self.b)):
            raise ValueError('Coeficientes deben ser un vector finito no vacío.')
        self.estado = np.zeros(len(self.b) - 1, dtype=dtype)
        self.dtype = dtype

    def procesar(self, bloque):
        x = np.asarray(bloque, dtype=self.dtype)
        if x.ndim != 1 or not np.all(np.isfinite(x)):
            raise ValueError('El bloque debe ser un vector finito.')
        y = np.empty_like(x)
        for n, muestra in enumerate(x):
            # Ecuación de diferencias FIR: a[0]=1, no hay realimentación.
            y[n] = self.b[0] * muestra + np.dot(self.b[1:], self.estado)
            if len(self.estado):
                self.estado[1:] = self.estado[:-1]
                self.estado[0] = muestra
        return y


def filtrar_por_bloques(x, b, n_bloque=1024, dtype=np.float64):
    if not isinstance(n_bloque, int) or n_bloque <= 0:
        raise ValueError('El tamaño del bloque debe ser positivo.')
    filtro = FIRCausal(b, dtype=dtype)
    x = np.asarray(x)
    salida = np.empty(len(x), dtype=dtype)
    for inicio in range(0, len(x), n_bloque):
        salida[inicio:inicio + n_bloque] = filtro.procesar(x[inicio:inicio + n_bloque])
    return salida


def caracterizar_filtro(b, spec, resumen, figuras):
    f, H = freqz(b, worN=16384, fs=spec['fs_hz'])
    omega = 2 * np.pi * f / spec['fs_hz']
    fase = np.unwrap(np.angle(H))
    retardo = -np.gradient(fase, omega)
    valida = abs(H) > 1e-3  # El retardo en ceros/rechazo profundo no es interpretable.
    fase_grafica = fase.copy()
    fase_grafica[~valida] = np.nan
    retardo[~valida] = np.nan
    fig, axs = plt.subplots(3, 1, figsize=(11, 9))
    axs[0].plot(f, 20 * np.log10(np.maximum(abs(H), 1e-12)))
    axs[0].axhline(-spec['atenuacion_min_db'], color='tab:red', ls='--', label='Rechazo requerido')
    axs[0].set(ylabel='Ganancia (dB)', ylim=(-120, 5), title=f'FIR pasa bajas: orden {len(b)-1}, {len(b)} coeficientes')
    axs[0].legend()
    axs[1].plot(f, fase_grafica)
    axs[1].set(ylabel='Fase desenrollada (rad)')
    axs[2].plot(f, retardo)
    axs[2].axhline(resumen['retardo_muestras'], color='tab:red', ls='--')
    axs[2].set(ylabel='Retardo de grupo (muestras)', ylim=(0, 1.2 * resumen['retardo_muestras']))
    for ax in axs:
        ax.axvspan(spec['paso_hz'], spec['rechazo_hz'], color='gray', alpha=.15)
        ax.set_xlabel('Frecuencia (Hz)')
        ax.grid(True, alpha=.25)
    guardar_figura(fig, figuras / 'fir_respuesta.png')
    # H(z) = (b0*z**M + ... + bM)/z**M. Sus M polos están en cero.
    ceros = np.roots(b)
    fig, ax = plt.subplots(figsize=(7, 7))
    angulo = np.linspace(0, 2 * np.pi, 500)
    ax.plot(np.cos(angulo), np.sin(angulo), '--', color='gray', label='Círculo unitario')
    ax.scatter(ceros.real, ceros.imag, facecolors='none', edgecolors='tab:blue', label='Ceros')
    ax.scatter([0], [0], marker='x', c='tab:red', label=f'Polo en 0, multiplicidad {len(b)-1}')
    ax.annotate(f'ROC causal: |z| > 0\nEstable: círculo unitario en la ROC', (.03, .03), xycoords='axes fraction')
    ax.set(xlabel='Parte real', ylabel='Parte imaginaria', title='Polos y ceros del FIR')
    ax.set_aspect('equal')
    ax.grid(True, alpha=.25)
    ax.legend(loc='upper right', fontsize=8)
    guardar_figura(fig, figuras / 'fir_polos_ceros.png')
    return ceros


def ejecutar_temporal(casos=None):
    spec = json.loads((RAIZ / 'metadatos/filtro_temporal.json').read_text(encoding='utf-8-sig'))
    b, resumen = disenar_fir(spec)
    casos = generar_todos() if casos is None else casos
    resultados = RAIZ / 'resultados'
    figuras = resultados / 'figuras'
    figuras.mkdir(parents=True, exist_ok=True)
    ceros = caracterizar_filtro(b, spec, resumen, figuras)
    guardar_csv(resultados / 'coeficientes_fir.csv', [{'k': k, 'b_k': float(v)} for k, v in enumerate(b)])
    # Solo cuantización de coeficientes Q1.15, NO simulación de aritmética fija.
    b_q15 = np.clip(np.rint(b * 32768), -32768, 32767) / 32768
    cuantizacion = []
    for formato, coef in [('float64', b), ('coef_float32', b.astype(np.float32).astype(float)), ('coef_Q1.15', b_q15)]:
        cuantizacion.append({'formato': formato, 'error_coef_max': float(max(abs(coef-b))), **medir_respuesta(coef, spec)})
    guardar_csv(resultados / 'fir_cuantizacion.csv', cuantizacion)
    filas, salidas = [], {}
    D, M = resumen['retardo_muestras'], resumen['orden']
    for nombre, datos in casos.items():
        if datos['metadatos']['fs_hz'] != spec['fs_hz']:
            raise ValueError('El filtro y la señal deben usar la misma fs.')
        x, s, ruido = datos['contaminada'], datos['limpia'], datos['ruido']
        N = datos['metadatos']['n_bloque']
        y = filtrar_por_bloques(x, b, N)
        referencia_biblioteca = lfilter(b, [1.0], x)
        error = float(max(abs(y-referencia_biblioteca)))
        if not np.allclose(y, referencia_biblioteca, atol=spec['tolerancia_atol'], rtol=spec['tolerancia_rtol']):
            raise AssertionError('La implementación propia no coincide con lfilter.')
        # Estas dos salidas se usan SOLO para evaluar conservación y ruido residual.
        ys = filtrar_por_bloques(s, b, N)
        yr = filtrar_por_bloques(ruido, b, N)
        # Evaluación alineada: excluye inicio y final, documenta exactamente el intervalo.
        L = len(s)
        if L <= M + D:
            raise ValueError('Registro demasiado corto para la evaluación alineada.')
        limpia_valida, entrada_valida = s[M:L-D], x[M:L-D]
        salida_valida = y[M+D:L]
        snr_entrada = snr_db(limpia_valida, entrada_valida)
        snr_salida = snr_db(limpia_valida, salida_valida)
        filas.append({'caso': nombre, 'error_vs_lfilter_max': error,
                      'snr_entrada_db': snr_entrada, 'snr_salida_alineada_db': snr_salida,
                      'mejora_snr_alineada_db': snr_salida-snr_entrada,
                      'mse_alineado': float(np.mean((limpia_valida-salida_valida)**2)),
                      'snr_salida_sin_alinear_db': snr_db(s, y),
                      'retardo_muestras': D, 'inicio_referencia': M,
                      'fin_referencia_exclusivo': L-D, 'inicio_salida': M+D,
                      'energia_util_conservada_pct': float(100*np.sum(ys[M+D:L]**2)/np.sum(limpia_valida**2)),
                      'atenuacion_ruido_total_db': float(10*np.log10(np.sum(ruido[M:L-D]**2)/np.sum(yr[M+D:L]**2))),
                      'pico_salida': float(max(abs(y))), 'muestras_fuera_rango_pcm': int(np.count_nonzero(abs(y)>1))})
        carpeta = resultados / 'temporal' / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(carpeta / 'salidas.npz', salida=y, salida_limpia=ys, salida_ruido=yr)
        # Sin normalización adicional: preservamos amplitudes para comparar métodos.
        wavfile.write(carpeta / 'salida_temporal.wav', spec['fs_hz'], pcm16(y))
        fig, axs = plt.subplots(2, 1, figsize=(12, 7))
        inicio = int(.1*spec['fs_hz'])
        vista = int(.01*spec['fs_hz'])
        tiempo = datos['tiempo'][inicio:inicio+vista]*1000
        axs[0].plot(tiempo, s[inicio:inicio+vista], label='Limpia')
        axs[0].plot(tiempo, x[inicio:inicio+vista], label='Contaminada', alpha=.45)
        axs[0].plot(tiempo, y[inicio+D:inicio+D+vista], label='FIR alineada solo para comparar', alpha=.8)
        axs[0].set(xlabel='Tiempo de referencia (ms)', ylabel='Amplitud', title=f'{nombre}: retardo real {D} muestras, {resumen["retardo_ms"]:.2f} ms')
        for etiqueta, senal in [('Limpia',s),('Contaminada',x),('FIR',y)]:
            esp = espectro_bloque(senal[inicio:inicio+N],spec['fs_hz'])
            axs[1].plot(esp['frecuencia_hz'],esp['magnitud_db'],label=etiqueta)
        axs[1].set(xlabel='Frecuencia (Hz)',ylabel='Amplitud (dB re 1)',ylim=(-110,5))
        for ax in axs:
            ax.grid(True,alpha=.25)
            ax.legend()
        guardar_figura(fig, figuras / f'{nombre}_fir.png')
        salidas[nombre] = y
    guardar_csv(resultados / 'temporal_metricas.csv',filas)
    detalle = {**spec, **resumen, 'b': b.tolist(), 'a': [1.0],
               'H_z': 'sum_{k=0}^{M} b[k] z^(-k)', 'roc_causal': '|z| > 0',
               'polos': [{'real':0,'imag':0,'multiplicidad':M}],
               'ceros': [{'real':float(z.real),'imag':float(z.imag)} for z in ceros],
               'estable_bibo':True, 'suma_absoluta_coeficientes':float(sum(abs(b))),
               'ram_coef_estado_float32_bytes':4*(len(b)+M),
               'ram_buffer_entrada_salida_float32_bytes':8*next(iter(casos.values()))['metadatos']['n_bloque'],
               'multiplicaciones_por_muestra':len(b), 'sumas_por_muestra':M,
               'cota_pico_salida_para_pico_entrada_08':float(.8*sum(abs(b))),
               'nota_memoria':'No incluye FFT, intérprete Python, biblioteca, pila ni comunicaciones.',
               'nota_cuantizacion':'Q1.15 cuantiza coeficientes; acumulación fija y saturación quedan por validar en hardware.'}
    (resultados / 'fir_diseno.json').write_text(json.dumps(detalle,indent=2),encoding='utf-8')
    print(f"FIR: orden {M}, {len(b)} coeficientes, retardo {D} muestras ({resumen['retardo_ms']:.2f} ms)")
    print(f"Rizado {resumen['rizado_pico_a_pico_db']:.6f} dB; rechazo mínimo {resumen['atenuacion_rechazo_min_db']:.3f} dB")
    for fila in filas:
        print(f"{fila['caso']}: error vs lfilter={fila['error_vs_lfilter_max']:.3e}; mejora SNR alineada={fila['mejora_snr_alineada_db']:.3f} dB")
    return {'coeficientes':b,'diseno':detalle,'metricas':filas,'salidas':salidas}


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ejecutar_temporal()
