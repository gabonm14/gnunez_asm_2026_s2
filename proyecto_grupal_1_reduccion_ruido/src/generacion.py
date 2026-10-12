"""Tres casos reproducibles, adaptados del generador proporcionado por el profesor.

Ejecutar desde la carpeta del proyecto: python -m src.generacion
Los algoritmos de filtrado deberán recibir solo la señal contaminada.
La señal limpia y el ruido aislado son referencias para evaluación.
"""
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt

RAIZ = Path(__file__).resolve().parents[1]


def potencia(x):
    """Potencia media de una secuencia real: promedio de x[n]**2."""
    x = np.asarray(x, dtype=np.float64)
    return float(np.mean(x * x))


def snr_db(limpia, observada):
    """SNR usando el error respecto a la referencia limpia."""
    ps = potencia(limpia)
    pe = potencia(np.asarray(observada) - np.asarray(limpia))
    if ps <= 0:
        raise ValueError('La referencia debe tener potencia positiva.')
    return float(10 * np.log10(ps / pe)) if pe > 0 else float('inf')


def validar_configuracion(config):
    fs = config['fs_hz']
    duracion = config['duracion_s']
    bloque = config['n_bloque']
    frecuencias = config['frecuencias_utiles_hz']
    amplitudes = config['amplitudes_utiles']
    fases = config['fases_utiles_grados']
    if fs <= 0 or duracion <= 0 or int(fs * duracion) < bloque:
        raise ValueError('Muestreo y duración deben permitir al menos un bloque.')
    if not isinstance(bloque, int) or bloque <= 0 or bloque & (bloque - 1):
        raise ValueError('n_bloque debe ser una potencia de dos positiva.')
    if not frecuencias or not len(frecuencias) == len(amplitudes) == len(fases):
        raise ValueError('Frecuencias, amplitudes y fases deben tener igual longitud.')
    if not all(0 < f < fs / 2 for f in frecuencias):
        raise ValueError('Frecuencias útiles deben estar entre 0 y Nyquist.')
    if not 0 < config['pico_maximo'] < 1:
        raise ValueError('pico_maximo debe estar entre 0 y 1.')
    if config['fade_ms'] < 0:
        raise ValueError('fade_ms no puede ser negativo.')
    ids = [caso['id'] for caso in config['casos']]
    semillas = [caso['semilla'] for caso in config['casos']]
    if len(ids) != len(set(ids)) or len(semillas) != len(set(semillas)):
        raise ValueError('Cada caso debe tener identificador y semilla diferentes.')
    for caso in config['casos']:
        if Path(caso['id']).name != caso['id'] or caso['id'] in ('.', '..'):
            raise ValueError('El identificador debe ser un nombre de carpeta simple.')
        if not np.isfinite(caso['snr_objetivo_db']):
            raise ValueError('La SNR objetivo debe ser finita.')
        if caso['tipo_ruido'] == 'tonal':
            if not 0 < caso['frecuencia_interferencia_hz'] < fs / 2:
                raise ValueError('Interferencia fuera del intervalo permitido.')
        elif caso['tipo_ruido'] == 'banda':
            bajo, alto = caso['banda_ruido_hz']
            if not 0 < bajo < alto < fs / 2:
                raise ValueError('Banda de ruido fuera del intervalo permitido.')
        else:
            raise ValueError('Este avance admite ruido tonal o de banda limitada.')


def generar_caso(config, caso):
    """Genera arrays float64 sin cambiar el estado aleatorio global.

    Primero se suaviza la señal útil, después se ajusta el ruido a la SNR
    objetivo y al final se aplica una única ganancia a las tres secuencias.
    """
    fs = config['fs_hz']
    t = np.arange(int(fs * config['duracion_s']), dtype=np.float64) / fs
    rng = np.random.default_rng(caso['semilla'])
    limpia = np.zeros_like(t)
    for f, a, fase in zip(config['frecuencias_utiles_hz'],
                          config['amplitudes_utiles'], config['fases_utiles_grados']):
        limpia += a * np.sin(2 * np.pi * f * t + np.deg2rad(fase))
    # Entrada/salida suave, igual al criterio del notebook del profesor.
    n_fade = min(int(fs * config['fade_ms'] / 1000), len(t) // 2)
    if n_fade > 0:
        rampa = np.sin(np.linspace(0, np.pi / 2, n_fade)) ** 2
        limpia[:n_fade] *= rampa
        limpia[-n_fade:] *= rampa[::-1]
    if caso['tipo_ruido'] == 'tonal':
        fase_ruido = rng.uniform(-np.pi, np.pi)
        ruido = np.sin(2 * np.pi * caso['frecuencia_interferencia_hz'] * t + fase_ruido)
    else:
        sos = butter(6, caso['banda_ruido_hz'], btype='bandpass', fs=fs, output='sos')
        # Solo genera ruido sintético offline; no es nuestro filtro causal.
        ruido = sosfiltfilt(sos, rng.standard_normal(len(t)))
    ps, pn = potencia(limpia), potencia(ruido)
    if min(ps, pn) <= 0:
        raise ValueError('Señal o ruido con potencia nula.')
    ruido *= np.sqrt(ps / (pn * 10 ** (caso['snr_objetivo_db'] / 10)))
    contaminada = limpia + ruido
    pico = max(np.max(np.abs(x)) for x in (limpia, ruido, contaminada))
    ganancia = config['pico_maximo'] / pico
    limpia, ruido, contaminada = [x * ganancia for x in (limpia, ruido, contaminada)]
    metadata = {
        **{k: v for k, v in config.items() if k != 'casos'}, **caso,
        'n_muestras': len(t), 'duracion_real_s': len(t) / fs,
        'duracion_bloque_s': config['n_bloque'] / fs,
        'separacion_bins_hz': fs / config['n_bloque'],
        'ganancia_comun': float(ganancia),
        'snr_obtenida_db': snr_db(limpia, contaminada),
        'formato_referencia': 'float64 en muestras.npz',
        'formato_wav': 'PCM16 mono; cuantización independiente de cada señal',
    }
    return {'tiempo': t, 'limpia': limpia, 'ruido': ruido,
            'contaminada': contaminada, 'metadatos': metadata}


def pcm16(x):
    """Cuantiza para audio; las métricas exactas usan los arrays float64."""
    return np.rint(np.clip(x, -1, 1) * 32767).astype(np.int16)


def exportar_caso(datos, carpeta):
    """Guarda referencias exactas, WAV y metadatos sin borrar la carpeta."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    fs = datos['metadatos']['fs_hz']
    np.savez_compressed(carpeta / 'muestras.npz',
                        **{k: datos[k] for k in ('tiempo', 'limpia', 'ruido', 'contaminada')})
    for nombre in ('limpia', 'ruido', 'contaminada'):
        wavfile.write(carpeta / f'{nombre}.wav', fs, pcm16(datos[nombre]))
    limpia_pcm = pcm16(datos['limpia']).astype(np.float64) / 32767
    mezcla_pcm = pcm16(datos['contaminada']).astype(np.float64) / 32767
    metadata = {**datos['metadatos'], 'snr_wav_db': snr_db(limpia_pcm, mezcla_pcm)}
    (carpeta / 'metadatos.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def generar_todos(ruta_config=None, salida=None):
    """Punto de entrada común al notebook y la terminal."""
    ruta_config = Path(ruta_config) if ruta_config else RAIZ / 'metadatos/configuraciones.json'
    salida = Path(salida) if salida else RAIZ / 'pruebas'
    # utf-8-sig acepta también los JSON que Windows guarde con BOM.
    config = json.loads(ruta_config.read_text(encoding='utf-8-sig'))
    validar_configuracion(config)
    resultados = {}
    for caso in config['casos']:
        datos = generar_caso(config, caso)
        exportar_caso(datos, salida / caso['id'])
        resultados[caso['id']] = datos
        print(f"{caso['id']}: {len(datos['limpia'])} muestras | "
              f"SNR objetivo {caso['snr_objetivo_db']:.6f} dB | "
              f"obtenida {datos['metadatos']['snr_obtenida_db']:.6f} dB")
    return resultados


if __name__ == '__main__':
    generar_todos()
