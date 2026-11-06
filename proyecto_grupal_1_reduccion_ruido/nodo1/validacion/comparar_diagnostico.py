"""Compara el diagnóstico del nodo 1 contra diagnosticar() de src/diagnostico.py.

    python nodo1/validacion/comparar_diagnostico.py --puerto /dev/ttyACM0   # placa
    python nodo1/validacion/comparar_diagnostico.py                         # host

Ambos reciben exactamente las mismas muestras float32 y los parámetros de metadatos/.
1) Un diagnóstico por caso (archivos de pruebas/ y señales sintéticas del barrido).
2) Diagnóstico periódico sobre una señal cuyo ruido cambia cada periodo: cada DIAG k se
   compara con diagnosticar(x[k*P:(k+1)*P]).
Diferencias esperadas: float32 frente a float64, DC por bloque frente a media global y la
mediana/MAD de impulsos por trozo de N en vez de global (solo cambia curtosis y tasa).
"""
import argparse
import csv
import json

import numpy as np

from conexion import NODO1, RAIZ, Conexion, parametros_proyecto
from src.diagnostico import contaminar_red, diagnosticar
from src.generacion import generar_caso

TOL_FRECUENCIA_HZ = 1.0
TOL_SNR_DB = 0.5
TOL_CURTOSIS_REL = 0.25


def casos_prueba(config, segundos):
    """Mezclas de pruebas/ (primer periodo) y casos sintéticos tipo barrido a SNR 5 dB."""
    L = int(segundos * config['fs_hz'])
    casos = {}
    for npz in sorted((RAIZ / 'pruebas').glob('caso_*/muestras.npz')):
        casos[npz.parent.name] = np.load(npz)['contaminada'][:L]
    corto = {**config, 'duracion_s': segundos}
    base = {'semilla': 20261201, 'snr_objetivo_db': 5.0}
    for f in (1900, 2600, 3300, 4400, 6000):
        casos[f'tonal_{f}'] = generar_caso(corto, {**base, 'tipo_ruido': 'tonal', 'frecuencia_interferencia_hz': f})['contaminada']
    for banda in ([2500, 3800], [3000, 5000]):
        casos[f'banda_{banda[0]}_{banda[1]}'] = generar_caso(corto, {**base, 'tipo_ruido': 'banda', 'banda_ruido_hz': banda})['contaminada']
    for tasa in (4, 10):
        casos[f'impulsivo_{tasa}'] = generar_caso(corto, {**base, 'tipo_ruido': 'impulsivo', 'impulsos_por_s': tasa})['contaminada']
    for f0 in (50, 60):
        casos[f'red_{f0}'] = contaminar_red(corto, f0, 5.0, base['semilla'])['contaminada']
    return casos


def comparar(nombre, nodo, ref, df):
    """Una fila con las diferencias; 'coincide' exige igualdad en lo que decide el nodo 3."""
    lin_n, lin_r = nodo['frecuencias_interferentes_hz'], ref['frecuencias_interferentes_hz']
    err_lin = max((abs(a - b) for a, b in zip(lin_n, lin_r)), default=0.0) if len(lin_n) == len(lin_r) else np.inf
    par = lambda a, b: (0.0 if a is None and b is None else
                        np.inf if a is None or b is None else max(abs(x - y) for x, y in zip(a, b)))
    uno = lambda a, b: 0.0 if a is None and b is None else np.inf if a is None or b is None else abs(a - b)
    fila = {'caso': nombre, 'tipo_python': ref['tipo'], 'tipo_nodo': nodo['tipo'],
            'confianza_python': ref['confianza'], 'confianza_nodo': nodo['confianza'],
            'n_lineas': f"{len(lin_r)}/{len(lin_n)}", 'error_lineas_hz': err_lin,
            'error_banda_hz': par(nodo['banda_ruido_hz'], ref['banda_ruido_hz']),
            'error_fin_banda_util_hz': uno(nodo['fin_banda_util_hz'], ref['fin_banda_util_hz']),
            'error_red_hz': uno(nodo['frecuencia_red_hz'], ref['frecuencia_red_hz']),
            'error_snr_db': uno(nodo['snr_estimada_db'], ref['snr_estimada_db']),
            'curtosis_python': ref['curtosis_diferencia'], 'curtosis_nodo': nodo['curtosis_diferencia'],
            'impulsos_python': ref['impulsos_por_s_estimados'] or '', 'impulsos_nodo': nodo['impulsos_por_s_estimados'] or '',
            'tiempo_nodo_ms': nodo['tiempo_calculo_ms']}
    fila['coincide'] = int(ref['tipo'] == nodo['tipo'] and set(ref['tipos']) == set(nodo['tipos'])
                           and ref['confianza'] == nodo['confianza'] and fila['error_lineas_hz'] <= TOL_FRECUENCIA_HZ
                           and fila['error_banda_hz'] <= df and fila['error_fin_banda_util_hz'] <= df
                           and fila['error_red_hz'] == 0 and fila['error_snr_db'] <= TOL_SNR_DB)
    c_r, c_n = ref['curtosis_diferencia'], nodo['curtosis_diferencia']
    fila['curtosis_ok'] = int(abs(c_n - c_r) <= TOL_CURTOSIS_REL * max(abs(c_r), 1.0))
    return fila


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--puerto', help='puerto serie de la placa; sin él se usa host/nodo1_host')
    args = parser.parse_args()
    parametros, cfg = parametros_proyecto()
    config = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))
    fs, N = parametros['fs_hz'], parametros['n_bloque']
    segundos = parametros['periodo_diag_ms'] / 1000
    df = fs / N
    con = Conexion(args.puerto)
    con.configurar(parametros)

    filas = []
    for nombre, x in casos_prueba(config, segundos).items():
        x = x.astype(np.float32)
        nodo = con.diagnosticar(x)[0]
        filas.append(comparar(nombre, nodo, diagnosticar(x.astype(np.float64), fs, N, cfg), df))

    # Repetición periódica: el ruido cambia en cada periodo y el nodo debe seguirlo.
    P = int(segundos * fs)
    corto = {**config, 'duracion_s': segundos}
    tramos = [generar_caso(corto, {'semilla': 7, 'snr_objetivo_db': 5.0, 'tipo_ruido': 'tonal',
                                   'frecuencia_interferencia_hz': 2500})['contaminada'],
              generar_caso(corto, {'semilla': 8, 'snr_objetivo_db': 5.0, 'tipo_ruido': 'tonal',
                                   'frecuencia_interferencia_hz': 3100})['contaminada'],
              generar_caso(corto, {'semilla': 9, 'snr_objetivo_db': 5.0, 'tipo_ruido': 'banda',
                                   'banda_ruido_hz': [3000, 5000]})['contaminada'],
              contaminar_red(corto, 60, 5.0, 10)['contaminada']]
    x = np.concatenate(tramos + [tramos[0][:P // 2]]).astype(np.float32)  # el resto incompleto se descarta
    periodicos = con.diagnosticar(x, periodico=True)
    if len(periodicos) != len(tramos):
        raise RuntimeError(f'Se esperaban {len(tramos)} diagnósticos periódicos y llegaron {len(periodicos)}.')
    for k, nodo in enumerate(periodicos):
        ref = diagnosticar(x[k * P:(k + 1) * P].astype(np.float64), fs, N, cfg)
        filas.append(comparar(f'periodico_{k + 1}', nodo, ref, df))
    tiempos = json.loads(con.comando('tiempos', 'TIEMPOS')[1])
    memoria = json.loads(con.comando('mem', 'MEM')[1])
    con.cerrar()

    for f in filas:
        print(f"{f['caso']:18s} python {f['tipo_python']:13s} {f['confianza_python']:4s} | nodo {f['tipo_nodo']:13s} "
              f"{f['confianza_nodo']:4s} | lineas {f['error_lineas_hz']:.3g} Hz  snr {f['error_snr_db']:.3g} dB  "
              f"curtosis {f['curtosis_python']:.3g}/{f['curtosis_nodo']:.3g}  "
              f"{'OK' if f['coincide'] and f['curtosis_ok'] else 'DIFIERE'}")
    salida = NODO1 / 'resultados'
    salida.mkdir(exist_ok=True)
    origen = con.origen.split(':')[0]
    with (salida / f'comparacion_diagnostico_{origen}.csv').open('w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    (salida / f'tiempos_memoria_{origen}.json').write_text(
        json.dumps({'origen': con.origen, 'tiempos': tiempos, 'memoria': memoria}, indent=2), encoding='utf-8')
    coinciden = sum(f['coincide'] and f['curtosis_ok'] for f in filas)
    print(f'{coinciden}/{len(filas)} diagnósticos coinciden con Python. Carga estimada '
          f"{tiempos['carga_cpu_pct']:.2f} % de CPU; diagnóstico medio {tiempos['diagnostico']['media_us']:.0f} us.")
    raise SystemExit(0 if coinciden == len(filas) else 1)


if __name__ == '__main__':
    main()
