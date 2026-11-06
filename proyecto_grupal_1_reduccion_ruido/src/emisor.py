"""Modelo del emisor: cuantización a 8 bits, PWM del ESP32 y filtro RC de reconstrucción.

Ejecutable con Run Python File en VS Code y con python -m src.emisor.
El emisor genera la señal útil ya cuantizada (duty de 8 bits), la convierte en PWM y
la pasa por el RC. La simulación del PWM usa pulsos con flancos fraccionarios dentro de
sub-intervalos (conserva el área, es decir la resolución de 8 bits) y el RC se discretiza
con retención de orden cero, que es exacta para entradas constantes por tramos.
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import cont2discrete, freqs, lfilter, lfilter_zi

if __package__ in (None, ''):
    from generacion import RAIZ, generar_caso, validar_configuracion
    from analisis import guardar_csv, guardar_figura
else:
    from .generacion import RAIZ, generar_caso, validar_configuracion
    from .analisis import guardar_csv, guardar_figura


def cargar_config():
    """Parámetros del emisor; la fs se toma de la especificación de los filtros."""
    cfg = json.loads((RAIZ / 'metadatos/emisor.json').read_text(encoding='utf-8-sig'))
    spec = json.loads((RAIZ / 'metadatos/filtro_temporal.json').read_text(encoding='utf-8-sig'))
    if cfg['orden_rc'] not in (1, 2):
        raise ValueError('orden_rc debe ser 1 o 2.')
    if cfg['osr_pwm'] < 1 or cfg['sub_muestras'] < 1 or cfg['bits_pwm'] < 1:
        raise ValueError('osr_pwm, sub_muestras y bits_pwm deben ser positivos.')
    return cfg, spec


def cuantizar(x, bits):
    """Código entero sin signo y valor reconstruido nominal en [-1, 1].

    x en [-1, 1] se mapea a 0..2^bits-1 con paso 2/(2^bits-1).
    """
    niveles = 2 ** bits - 1
    codigo = np.clip(np.rint((np.asarray(x) + 1) * niveles / 2), 0, niveles).astype(np.int64)
    return codigo, codigo * 2 / niveles - 1


def sqnr_teorica_db(x, bits):
    """Potencia de la señal sobre el ruido uniforme Delta^2/12 con Delta = 2/(2^bits-1)."""
    delta = 2 / (2 ** bits - 1)
    return float(10 * np.log10(np.mean(np.asarray(x) ** 2) / (delta ** 2 / 12)))


def razon_duty(codigo, bits):
    """El LEDC del ESP32 compara el contador con el duty: razón = duty / 2^bits."""
    return np.asarray(codigo) / 2 ** bits


def divisor_ledc(cfg, fs):
    """Divisor fraccionario del LEDC (resolución 1/256) y portadora real obtenida."""
    f_obj = fs * cfg['osr_pwm']
    div = cfg['reloj_ledc_hz'] / (f_obj * 2 ** cfg['bits_pwm'])
    if div < 1:
        raise ValueError(f'Portadora inalcanzable: el máximo con {cfg["bits_pwm"]} bits es '
                         f'{cfg["reloj_ledc_hz"] / 2 ** cfg["bits_pwm"]:.0f} Hz.')
    div_q = round(div * 256) / 256
    f_real = cfg['reloj_ledc_hz'] / (div_q * 2 ** cfg['bits_pwm'])
    return {'f_pwm_objetivo_hz': f_obj, 'divisor_ideal': div, 'divisor_ledc': div_q,
            'f_pwm_real_hz': f_real, 'desajuste_pct': 100 * (f_real / f_obj - 1),
            'f_pwm_max_hz': cfg['reloj_ledc_hz'] / 2 ** cfg['bits_pwm']}


def funcion_transferencia_rc(cfg):
    """H(s) del RC pasivo sin buffer (la 2.ª etapa carga a la 1.ª): num, den en s."""
    R1, C1 = cfg['R1_ohm'], cfg['C1_nf'] * 1e-9
    if cfg['orden_rc'] == 1:
        return [1.0], [R1 * C1, 1.0]
    R2, C2 = cfg['R2_ohm'], cfg['C2_nf'] * 1e-9
    return [1.0], [R1 * C1 * R2 * C2, R1 * C1 + R2 * C2 + R1 * C2, 1.0]


def respuesta_rc(cfg, f_hz):
    num, den = funcion_transferencia_rc(cfg)
    _, H = freqs(num, den, worN=2 * np.pi * np.asarray(f_hz, dtype=float))
    return H


def retardo_grupo_dc_s(cfg):
    """Para H = 1/(1 + a1 s + a2 s^2) el retardo de grupo en DC es a1."""
    return float(funcion_transferencia_rc(cfg)[1][-2])


def rc_discreto(cfg, fs):
    """RC a la frecuencia de simulación fs*osr*sub, exacto para pulsos constantes por tramo."""
    fsim = fs * cfg['osr_pwm'] * cfg['sub_muestras']
    num, den = funcion_transferencia_rc(cfg)
    b, a, _ = cont2discrete((num, den), 1 / fsim, method='zoh')
    return np.ravel(b), np.ravel(a), fsim


def _pulsos(razon, osr, sub):
    """Entrada al RC en [0, 1]: por periodo PWM, fracción de cada sub-intervalo en alto."""
    parcial = np.clip(razon[:, None] * sub - np.arange(sub)[None, :], 0, 1)
    return np.repeat(parcial[:, None, :], osr, axis=1).reshape(-1)


def simular_pwm_rc(razon, cfg, fs):
    """Salida del RC en voltios, muestreada a fs, y rizado de la portadora.

    El estado del filtro se conserva entre bloques. La salida se toma en el último
    sub-intervalo de cada periodo de muestreo, como lo haría un ADC sin antialiasing.
    """
    razon = np.asarray(razon, dtype=float)
    b, a, _ = rc_discreto(cfg, fs)
    osr, sub, vdd = cfg['osr_pwm'], cfg['sub_muestras'], cfg['vdd_v']
    por_muestra = osr * sub
    zi = lfilter_zi(b, a) * vdd * razon[0]
    salida = np.empty(len(razon))
    rizado = []
    for inicio in range(0, len(razon), cfg['bloque_simulacion_muestras']):
        r = razon[inicio:inicio + cfg['bloque_simulacion_muestras']]
        v, zi = lfilter(b, a, vdd * _pulsos(r, osr, sub), zi=zi)
        salida[inicio:inicio + len(r)] = v[por_muestra - 1::por_muestra]
        periodos = v.reshape(-1, sub)
        rizado.append(np.ptp(periodos, axis=1))
    rizado = np.concatenate(rizado)
    return salida, rizado


def emitir(x, cfg, fs):
    """Cadena completa para una señal en [-1, 1].

    Devuelve la salida real (duty cuantizado) y la de referencia (duty continuo, sin
    cuantizar) a través del MISMO PWM+RC. Su diferencia aísla la cuantización.
    """
    codigo, x_rec = cuantizar(x, cfg['bits_pwm'])
    niveles = 2 ** cfg['bits_pwm'] - 1
    razon_q = razon_duty(codigo, cfg['bits_pwm'])
    razon_c = np.clip((np.asarray(x) + 1) * niveles / 2, 0, niveles) / 2 ** cfg['bits_pwm']
    y_q, rizado = simular_pwm_rc(razon_q, cfg, fs)
    y_c, _ = simular_pwm_rc(razon_c, cfg, fs)
    return {'codigo': codigo, 'x_reconstruida': x_rec, 'salida_v': y_q,
            'salida_continua_v': y_c, 'rizado_pp_v': rizado}


def metricas_emisor(x, e, cfg, spec):
    x = np.asarray(x)
    ac = lambda v: v - v.mean()
    ruido = ac(e['salida_v']) - ac(e['salida_continua_v'])
    potencia = lambda v: float(np.mean(v ** 2))
    return {'sqnr_cuantizacion_medida_db': float(10 * np.log10(potencia(x) / potencia(e['x_reconstruida'] - x))),
            'sqnr_cuantizacion_teorica_db': sqnr_teorica_db(x, cfg['bits_pwm']),
            'sqnr_cadena_pwm_rc_db': float(10 * np.log10(potencia(ac(e['salida_continua_v'])) / potencia(ruido))),
            'offset_dc_v': float(e['salida_v'].mean()),
            'codigos_saturados': int(np.count_nonzero((e['codigo'] == 0) | (e['codigo'] == 2 ** cfg['bits_pwm'] - 1))),
            'pico_salida_v': float(np.max(abs(ac(e['salida_v']))))}


def rizado_portadora(cfg, fs, duties=np.linspace(.1, .9, 9)):
    """Rizado pico a pico de la portadora con duty constante (sin pendiente de señal).

    Es lo que se mediría en un osciloscopio con una entrada en reposo. Devuelve el
    peor caso del barrido y el duty donde ocurre.
    """
    picos = [float(simular_pwm_rc(np.full(300, d), cfg, fs)[1][-1]) for d in duties]
    k = int(np.argmax(picos))
    return {'rizado_portadora_pp_max_mv': 1000 * picos[k], 'duty_peor_caso': float(duties[k]),
            'rizado_portadora_pp_max_dbfs': float(20 * np.log10(picos[k] / cfg['vdd_v']))}


def figuras_emisor(x, e, cfg, spec, ruta_cuantizacion, ruta_cadena):
    fs = spec['fs_hz']
    inicio = int(.5 * fs)
    n = int(.005 * fs)
    t = np.arange(n) / fs * 1000
    fig, axs = plt.subplots(2, 1, figsize=(11, 8))
    axs[0].plot(t, x[inicio:inicio + n], label='Señal ideal')
    axs[0].step(t, e['x_reconstruida'][inicio:inicio + n], where='post', label=f'Cuantizada a {cfg["bits_pwm"]} bits')
    axs[0].set(xlabel='Tiempo (ms)', ylabel='Amplitud', title='Cuantización del duty')
    error = e['x_reconstruida'] - x
    ventana = np.hanning(4096)
    esp = np.abs(np.fft.rfft(error[:4096] * ventana)) / (ventana.sum() / 2)
    f = np.fft.rfftfreq(4096, 1 / fs)
    axs[1].plot(f, 20 * np.log10(np.maximum(esp, 1e-12)))
    axs[1].set(xlabel='Frecuencia (Hz)', ylabel='Error de cuantización (dB re 1)', title='Espectro del error')
    for ax in axs:
        ax.grid(True, alpha=.25)
    axs[0].legend()
    guardar_figura(fig, ruta_cuantizacion)

    fig, axs = plt.subplots(2, 1, figsize=(11, 8))
    b, a, fsim = rc_discreto(cfg, fs)
    # Un escalón de duty 50 % -> 25 % muestra el rizado y la constante de tiempo del RC.
    por_muestra = cfg['osr_pwm'] * cfg['sub_muestras']
    pulsos = _pulsos(np.array([.25, .25]), cfg['osr_pwm'], cfg['sub_muestras'])
    v, _ = lfilter(b, a, cfg['vdd_v'] * pulsos, zi=lfilter_zi(b, a) * cfg['vdd_v'] * .5)
    tt = np.arange(len(pulsos)) / fsim * 1e6
    axs[0].plot(tt, cfg['vdd_v'] * pulsos, drawstyle='steps-post', alpha=.5, label='PWM (duty 25 %)')
    axs[0].plot(tt, v, label='Salida del RC (parte de duty 50 %)')
    axs[0].set(xlabel='Tiempo (µs)', ylabel='Voltaje (V)', title='PWM y salida del filtro RC')
    frec = np.logspace(2, np.log10(fs * cfg['osr_pwm']) + .3, 600)
    mag = 20 * np.log10(abs(respuesta_rc(cfg, frec)))
    axs[1].semilogx(frec, mag, label=f'RC de orden {cfg["orden_rc"]}')
    for marca, etiqueta in [(spec['paso_hz'], 'paso'), (spec['rechazo_hz'], 'rechazo'),
                            (fs / 2, 'fs/2'), (fs * cfg['osr_pwm'], 'portadora PWM')]:
        axs[1].axvline(marca, ls='--', color='gray', alpha=.6)
        axs[1].annotate(etiqueta, (marca, -5), rotation=90, fontsize=8, va='top')
    axs[1].set(xlabel='Frecuencia (Hz)', ylabel='Ganancia (dB)', ylim=(-100, 5), title='Respuesta del RC de reconstrucción')
    for ax in axs:
        ax.grid(True, alpha=.25, which='both')
        ax.legend()
    guardar_figura(fig, ruta_cadena)


def ejecutar_emisor(casos=None):
    cfg, spec = cargar_config()
    fs = spec['fs_hz']
    config = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))
    validar_configuracion(config)
    if config['fs_hz'] != fs:
        raise ValueError('El emisor y los filtros deben usar la misma fs.')
    # generar_caso no escribe en disco: no se tocan los archivos de pruebas/.
    casos = {c['id']: generar_caso(config, c) for c in config['casos']} if casos is None else casos
    resultados = RAIZ / 'resultados'
    figuras = resultados / 'figuras'
    figuras.mkdir(parents=True, exist_ok=True)
    filas, emisiones = [], {}
    for nombre, datos in casos.items():
        x = datos['limpia']
        e = emitir(x, cfg, fs)
        emisiones[nombre] = e
        filas.append({'caso': nombre, **metricas_emisor(x, e, cfg, spec)})
        if len(emisiones) == 1:
            figuras_emisor(x, e, cfg, spec, figuras / 'emisor_cuantizacion.png', figuras / 'emisor_pwm_rc.png')
    guardar_csv(resultados / 'emisor_metricas.csv', filas)
    f_notables = [spec['paso_hz'], spec['rechazo_hz'], fs / 2, fs * cfg['osr_pwm']]
    mag_db = 20 * np.log10(abs(respuesta_rc(cfg, f_notables)))
    num, den = funcion_transferencia_rc(cfg)
    polos = np.roots(den)
    diseno = {**cfg, 'fs_hz': fs, **divisor_ledc(cfg, fs),
              'H_s_den': den, 'polos_s_rad_por_s': [float(p.real) for p in polos],
              'frecuencia_3db_hz': float(np.interp(3, -20 * np.log10(abs(respuesta_rc(cfg, np.linspace(1, fs, 20000)))),
                                                  np.linspace(1, fs, 20000))),
              **rizado_portadora(cfg, fs),
              'ganancia_rc_db': {'paso_hz': float(mag_db[0]), 'rechazo_hz': float(mag_db[1]),
                                 'nyquist_hz': float(mag_db[2]), 'portadora_pwm_hz': float(mag_db[3])},
              'retardo_grupo_dc_us': 1e6 * retardo_grupo_dc_s(cfg),
              'retardo_grupo_dc_muestras': retardo_grupo_dc_s(cfg) * fs,
              'sqnr_teorica_escala_completa_db': 6.02 * cfg['bits_pwm'] + 1.76,
              'nota': 'El RC sin buffer se carga a sí mismo; la impedancia de salida del GPIO y la '
                      'carga del ADC del nodo 1 no están modeladas y deben medirse.'}
    (resultados / 'emisor_diseno.json').write_text(json.dumps(diseno, indent=2), encoding='utf-8')
    div = divisor_ledc(cfg, fs)
    print(f"{cfg['mcu']}: PWM {div['f_pwm_real_hz']:.0f} Hz (divisor {div['divisor_ledc']}), "
          f"{cfg['bits_pwm']} bits; RC orden {cfg['orden_rc']}: -3 dB en {diseno['frecuencia_3db_hz']:.0f} Hz")
    for fila in filas:
        print(f"{fila['caso']}: SQNR cuant. {fila['sqnr_cuantizacion_medida_db']:.1f} dB "
              f"(teórica {fila['sqnr_cuantizacion_teorica_db']:.1f}); cadena {fila['sqnr_cadena_pwm_rc_db']:.1f} dB; "
              f"offset DC {fila['offset_dc_v']:.3f} V")
    print(f"Rizado de portadora (peor caso, duty {diseno['duty_peor_caso']:.1f}): "
          f"{diseno['rizado_portadora_pp_max_mv']:.2f} mV pp")
    return {'diseno': diseno, 'metricas': filas, 'emisiones': emisiones}


if __name__ == '__main__':
    plt.switch_backend('Agg')
    ejecutar_emisor()
