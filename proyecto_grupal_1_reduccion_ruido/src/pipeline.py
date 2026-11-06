"""Orquestador end-to-end: emisor -> ruido -> nodo 1 -> nodo 2 -> nodo 3 -> métricas.

Ejecutable con Run Python File en VS Code y con python -m src.pipeline
(opciones: --casos caso_1 caso_2, --config ruta.json). Todo se pasa en memoria entre etapas:
  emisor    PWM del ESP32 + RC, en voltios (con su nivel de DC)
  ruido     se suma en voltios a la salida del emisor
  nodo 1    ADC de 12 bits, eliminación de DC, diagnóstico y parámetros para los otros nodos
  nodo 2    FIR o IIR causal por bloques, con estado
  nodo 3    FFT/IFFT por bloques, con banda fija y con banda del diagnóstico
La señal limpia de referencia es la que sale del emisor, de modo que las métricas aíslan
la reducción de ruido; el error propio del emisor se reporta aparte. Los tiempos son de la
implementación en Python, no del firmware.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter
import numpy as np
import matplotlib.pyplot as plt

if __package__ in (None, ''):
    from generacion import RAIZ, generar_caso, snr_db
    from analisis import guardar_csv, guardar_figura
    from filtros_temporales import disenar_fir, filtrar_por_bloques
    from filtros_iir import (disenar_iir, filtrar_sos_por_bloques, muestras_asentamiento,
                             retardo_efectivo, retardo_grupo, cargar_specs)
    from filtrado_espectral import reducir_espectral
    from emisor import cargar_config as cargar_emisor, emitir, metricas_emisor
    from diagnostico import diagnosticar, adaptar_config_espectral, sin_espectro, cargar_config as cargar_diag
    from metricas import frecuencia_dominante, medir_calidad
    from comparacion import verificar_criterios
else:
    from .generacion import RAIZ, generar_caso, snr_db
    from .analisis import guardar_csv, guardar_figura
    from .filtros_temporales import disenar_fir, filtrar_por_bloques
    from .filtros_iir import (disenar_iir, filtrar_sos_por_bloques, muestras_asentamiento,
                              retardo_efectivo, retardo_grupo, cargar_specs)
    from .filtrado_espectral import reducir_espectral
    from .emisor import cargar_config as cargar_emisor, emitir, metricas_emisor
    from .diagnostico import diagnosticar, adaptar_config_espectral, sin_espectro, cargar_config as cargar_diag
    from .metricas import frecuencia_dominante, medir_calidad
    from .comparacion import verificar_criterios

METODOS = ('FIR', 'IIR', 'espectral_fijo', 'espectral_adaptativo')


def leer_json(nombre):
    return json.loads((RAIZ / 'metadatos' / nombre).read_text(encoding='utf-8-sig'))


def cargar_configuraciones(ruta_pipeline=None):
    """Todas las configuraciones, validando que compartan fs y bloque."""
    pipe = (json.loads(Path(ruta_pipeline).read_text(encoding='utf-8-sig')) if ruta_pipeline
            else leer_json('pipeline.json'))
    cfg = {'pipeline': pipe, 'temporal': leer_json('filtro_temporal.json'),
           'espectral': leer_json('filtro_espectral.json'), 'iir': cargar_specs()[1],
           'comparacion': leer_json('comparacion.json'), 'diagnostico': cargar_diag(),
           'emisor': cargar_emisor()[0], 'generacion': leer_json('configuraciones.json')}
    desconocidos = set(pipe['metodos']) - set(METODOS)
    if desconocidos:
        raise ValueError(f'Métodos desconocidos: {sorted(desconocidos)}. Disponibles: {METODOS}.')
    fs = cfg['temporal']['fs_hz']
    if cfg['espectral']['fs_hz'] != fs or cfg['generacion']['fs_hz'] != fs:
        raise ValueError('Todas las etapas deben usar la misma fs.')
    return cfg


def nodo_emisor(limpia, cfg, fs):
    """Salida del emisor en voltios (con DC) y su calidad propia."""
    e = emitir(limpia, cfg['emisor'], fs)
    return e['salida_v'], metricas_emisor(limpia, e, cfg['emisor'], cfg['temporal'])


def nodo_adquisicion(v_mezcla, ganancia_nominal, cfg, fs):
    """ADC, eliminación de DC y normalización; devuelve la mezcla que ven los nodos 2 y 3."""
    bits, vref = cfg['pipeline']['adc_bits'], cfg['pipeline']['vref_v']
    niveles = 2 ** bits - 1
    saturadas = int(np.count_nonzero((v_mezcla < 0) | (v_mezcla > vref)))
    codigo = np.rint(np.clip(v_mezcla, 0, vref) / vref * niveles)
    v_adc = codigo * vref / niveles
    offset = float(v_adc.mean())
    return (v_adc - offset) / ganancia_nominal, {'adc_bits': bits, 'offset_dc_v': offset,
                                                   'muestras_saturadas_adc': saturadas,
                                                   'paso_adc_v': vref / niveles}


def nodo_analisis(x, cfg, fs):
    """Diagnóstico sobre los primeros segundos de la mezcla y parámetros para el nodo 3."""
    N = cfg['espectral']['n_bloque']
    n = min(len(x), max(N, int(cfg['pipeline']['segundos_diagnostico'] * fs)))
    t0 = perf_counter()
    diag = diagnosticar(x[:n], fs, N, cfg['diagnostico'])
    config_adaptada, usa = adaptar_config_espectral(diag, cfg['espectral'], fs)
    return diag, config_adaptada, usa, 1000 * (perf_counter() - t0)


def preparar_nodo2(cfg, fs):
    """FIR o IIR con la misma interfaz: función senal -> salida, más datos del diseño."""
    b, res_fir = disenar_fir(cfg['temporal'])
    sos, res_iir = disenar_iir(cfg['temporal'], cfg['iir'], cfg['pipeline']['familia_iir'])
    N = cfg['espectral']['n_bloque']
    f, _, tau = retardo_grupo(sos, fs)
    paso = f <= cfg['temporal']['paso_hz']
    return {'FIR': lambda s: filtrar_por_bloques(s, b, N),
            'IIR': lambda s: filtrar_sos_por_bloques(s, sos, N),
            'diseno': {'b': b, 'orden_fir': res_fir['orden'], 'retardo_fir': res_fir['retardo_muestras'],
                       'sos': sos, 'asentamiento_iir': muestras_asentamiento(sos, cfg['iir']['umbral_asentamiento']),
                       'retardo_iir_max': int(np.ceil(np.nanmax(tau[paso]))),
                       'retardo_iir_medio': float(np.nanmean(tau[paso]))}}


def procesar_nodo3(x, s, r, config):
    """Máscaras aprendidas de la mezcla y aplicadas a señal y ruido por separado."""
    t0 = perf_counter()
    p = reducir_espectral(x, config)
    ms_por_marco = 1000 * (perf_counter() - t0) / len(p['inicios'])
    ys = reducir_espectral(s, config, ganancias=p['ganancias'])['salida']
    yr = reducir_espectral(r, config, ganancias=p['ganancias'])['salida']
    if not np.allclose(p['salida'], ys + yr, atol=1e-12, rtol=1e-10):
        raise AssertionError('La descomposición espectral no reconstruye la salida.')
    return p['salida'], ys, yr, ms_por_marco


def correr_caso(nombre, datos, cfg, nodo2):
    fs = cfg['temporal']['fs_hz']
    N, H = cfg['espectral']['n_bloque'], cfg['espectral']['salto']
    metodos = cfg['pipeline']['metodos']
    d2 = nodo2['diseno']
    ganancia_nominal = cfg['emisor']['vdd_v'] * (2 ** cfg['emisor']['bits_pwm'] - 1) / 2 ** (cfg['emisor']['bits_pwm'] + 1)

    # 1) Emisor y ruido, en voltios. El ruido conserva la escala relativa del caso.
    v_emisor, calidad_emisor = nodo_emisor(datos['limpia'], cfg, fs)
    v_mezcla = v_emisor + datos['ruido'] * ganancia_nominal
    # 2) Nodo 1: la referencia es lo que el emisor realmente entregó (sin DC).
    x, info_adc = nodo_adquisicion(v_mezcla, ganancia_nominal, cfg, fs)
    s = (v_emisor - v_emisor.mean()) / ganancia_nominal
    r = x - s  # ruido total visto por los nodos: ruido añadido + cuantización del ADC.
    diag, config_adaptada, usa, t_diag = nodo_analisis(x, cfg, fs)
    snr_entrada = snr_db(s, x)

    # 3) Procesamiento. Cada salida se descompone en señal filtrada y ruido filtrado.
    salidas, tiempos = {}, {}
    config_espectral = {'espectral_fijo': cfg['espectral'], 'espectral_adaptativo': config_adaptada}
    for metodo in metodos:
        t0 = perf_counter()
        if metodo in ('FIR', 'IIR'):
            y = nodo2[metodo](x)
            tiempos[metodo] = 1000 * (perf_counter() - t0) / int(np.ceil(len(x) / N))
            ys, yr = nodo2[metodo](s), nodo2[metodo](r)
            if not np.allclose(y, ys + yr, atol=1e-9, rtol=1e-8):
                raise AssertionError(f'{metodo}: la descomposición no reconstruye la salida.')
        else:
            y, ys, yr, tiempos[metodo] = procesar_nodo3(x, s, r, config_espectral[metodo])
        salidas[metodo] = (y, ys, yr)

    # 4) Intervalo común y retardos de cada método.
    L = len(s)
    inicio = max(N, d2['orden_fir'], d2['asentamiento_iir'])
    retardos = {'sin_filtrar': 0, 'espectral_fijo': 0, 'espectral_adaptativo': 0, 'FIR': d2['retardo_fir']}
    if 'IIR' in salidas:
        retardos['IIR'] = retardo_efectivo(s, salidas['IIR'][1], inicio, d2['retardo_iir_max'])
    fin = L - N - max(retardos.values())
    if fin <= inicio:
        raise ValueError('Registro insuficiente para el intervalo común.')
    v = slice(inicio, fin)
    fdom = (datos['metadatos']['frecuencia_interferencia_hz'] if datos['metadatos'].get('tipo_ruido') == 'tonal'
            else frecuencia_dominante(r[v], fs))
    latencia = {'sin_filtrar': 0.0, 'FIR': 1000 * d2['retardo_fir'] / fs, 'IIR': 1000 * d2['retardo_iir_medio'] / fs,
                'espectral_fijo': 1000 * N / fs, 'espectral_adaptativo': 1000 * N / fs}
    filas = []
    snr_sep_in = float(10 * np.log10(np.sum(s[v] ** 2) / np.sum(r[v] ** 2)))
    for metodo in ('sin_filtrar', *metodos):
        y, ys, yr = (x, s, r) if metodo == 'sin_filtrar' else salidas[metodo]
        lag = retardos[metodo]
        vl = slice(inicio + lag, fin + lag)
        medidas = medir_calidad(s[v], x[v], y[vl], ys[vl], yr[vl], fs, fdom)
        snr_sep = float(10 * np.log10(np.sum(ys[vl] ** 2) / np.sum(yr[vl] ** 2)))
        fila = {'caso': nombre, 'metodo': metodo, **medidas, 'snr_salida_separada_db': snr_sep,
                'mejora_snr_separada_db': snr_sep - snr_sep_in, 'compensacion_muestras': lag,
                'latencia_algoritmica_ms': latencia[metodo],
                'tiempo_python_por_bloque_ms': tiempos.get(metodo, 0.0),
                'usa_diagnostico': int(usa) if metodo == 'espectral_adaptativo' else 0,
                'muestras_evaluadas': fin - inicio,
                'pico_salida_registro': float(max(abs(y))), 'muestras_fuera_rango_pcm': int(np.count_nonzero(abs(y) > 1))}
        fila['criterio_calidad'] = verificar_criterios(fila, cfg['comparacion']['criterios_predefinidos'])
        filas.append(fila)
    etapas = {'caso': nombre, 'snr_entrada_real_db': snr_entrada, **{f'emisor_{k}': v_ for k, v_ in calidad_emisor.items()},
              **{f'nodo1_{k}': v_ for k, v_ in info_adc.items()},
              'nodo1_tipo_diagnosticado': diag['tipo'], 'nodo1_confianza': diag['confianza'],
              'nodo1_fin_banda_util_hz': diag['fin_banda_util_hz'] or '', 'nodo1_usa_diagnostico': int(usa),
              'nodo1_tiempo_diagnostico_ms': t_diag}
    return filas, etapas, sin_espectro(diag), salidas


def figura_resumen(filas, casos, ruta):
    metodos = [m for m in METODOS if any(f['metodo'] == m for f in filas)]
    pos = np.arange(len(casos))
    ancho = .8 / len(metodos)
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))
    for j, m in enumerate(metodos):
        g = [f for f in filas if f['metodo'] == m]
        axs[0].bar(pos + (j - (len(metodos) - 1) / 2) * ancho, [f['mejora_snr_separada_db'] for f in g], ancho, label=m)
        axs[1].bar(pos + (j - (len(metodos) - 1) / 2) * ancho, [f['latencia_algoritmica_ms'] for f in g], ancho, label=m)
    axs[0].set(ylabel='Mejora de SNR (dB), independiente del retardo', title='Reducción de ruido por método')
    axs[1].set(ylabel='Latencia algorítmica (ms)', title='Latencia por método')
    for ax in axs:
        ax.set_xticks(pos, casos)
        ax.grid(True, axis='y', alpha=.25)
        ax.legend(fontsize=8)
    guardar_figura(fig, ruta)


def correr_pipeline(ruta_config=None, casos=None, ids=None, guardar=True):
    cfg = cargar_configuraciones(ruta_config)
    fs = cfg['temporal']['fs_hz']
    if casos is None:
        # generar_caso no escribe en disco: no se tocan los archivos de pruebas/.
        pedidos = ids or cfg['pipeline']['casos']
        casos = {c['id']: generar_caso(cfg['generacion'], c) for c in cfg['generacion']['casos']
                 if pedidos is None or c['id'] in pedidos}
    if not casos:
        raise ValueError('No hay casos que ejecutar.')
    nodo2 = preparar_nodo2(cfg, fs)
    filas, etapas, diagnosticos, salidas = [], [], {}, {}
    for nombre, datos in casos.items():
        f, e, d, s = correr_caso(nombre, datos, cfg, nodo2)
        filas += f
        etapas.append(e)
        diagnosticos[nombre] = d
        salidas[nombre] = s
        mejor = {x['metodo']: x['mejora_snr_separada_db'] for x in f if x['metodo'] != 'sin_filtrar'}
        print(f"{nombre}: SNR entrada {e['snr_entrada_real_db']:.2f} dB; diagnóstico {e['nodo1_tipo_diagnosticado']} "
              f"({e['nodo1_confianza']}); mejora " + ', '.join(f'{k} {v:.1f} dB' for k, v in mejor.items()))
    if guardar:
        res = RAIZ / 'resultados'
        guardar_csv(res / 'pipeline_metricas.csv', filas)
        guardar_csv(res / 'pipeline_etapas.csv', etapas)
        (res / 'pipeline_diagnosticos.json').write_text(json.dumps(diagnosticos, indent=2), encoding='utf-8')
        figura_resumen(filas, list(casos), res / 'figuras' / 'pipeline_resumen.png')
        lineas = ['# Pipeline end-to-end\n', 'Referencia: la señal que entrega el emisor. Mejora separada = independiente del retardo.\n',
                  '| Caso | Método | MSE | Mejora alineada (dB) | Mejora separada (dB) | Energía útil (%) | Latencia (ms) | Criterio |',
                  '|---|---|---:|---:|---:|---:|---:|---|']
        lineas += [f"| {f['caso']} | {f['metodo']} | {f['mse']:.4g} | {f['mejora_snr_db']:.2f} | {f['mejora_snr_separada_db']:.2f} | "
                   f"{f['energia_util_conservada_pct']:.2f} | {f['latencia_algoritmica_ms']:.2f} | {f['criterio_calidad']} |" for f in filas]
        (res / 'pipeline_resumen.md').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return {'metricas': filas, 'etapas': etapas, 'diagnosticos': diagnosticos, 'salidas': salidas}


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ap = argparse.ArgumentParser(description='Pipeline end-to-end del sistema de reducción de ruido.')
    ap.add_argument('--config', help='JSON alterno al de metadatos/pipeline.json')
    ap.add_argument('--casos', nargs='+', help='ids de casos a ejecutar (por defecto, los del JSON)')
    a = ap.parse_args()
    correr_pipeline(a.config, ids=a.casos)
