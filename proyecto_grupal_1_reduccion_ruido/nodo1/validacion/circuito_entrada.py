"""Entrada del nodo 1: micrófono MAX4466 a 3.3 V y RC anti-aliasing de dos etapas hacia el ADC.

    MAX4466 OUT ── R1 ── B ── R2 ── A ──► GPIO34 (ADC1_CH6)
    (DC ≈ 1.65 V)        │          │
                         C1         C2
                         │          │
                        GND        GND

El módulo ya entrega la señal centrada en VCC/2, así que no hace falta acople ni divisor:
el RC deja pasar la DC sin cambio. Las dos etapas cargadas no son dos filtros independientes:
    H(s) = 1 / (R1 C1 R2 C2 s^2 + (R1 C1 + R2 C2 + R1 C2) s + 1)
El MAX4466 tiene un producto ganancia-ancho de banda de ~200 kHz (hoja de datos): con ganancia
G su respuesta cae como un polo en ~200 kHz / G. Se suma a la del RC y depende del potenciómetro.

    python nodo1/validacion/circuito_entrada.py
"""
import json

import matplotlib.pyplot as plt
import numpy as np

from conexion import NODO1

VDD = 3.3
DC_MICROFONO = VDD / 2
RANGO_ADC_V = (0.15, 2.45)  # rango lineal recomendado del ESP32 con ADC_ATTEN_DB_12 (Espressif)
MV_POR_CODIGO = 3100 / 4095  # aproximado con 12 dB; verificar con min_mv/max_mv del comando "adc"
FS = 16000
TONOS_UTILES = (440, 880, 1320)
INTERFERENCIAS = (2500, 2508)
F_RUIDO_MAX = 7500           # ruido de banda más alto de los casos (caso_5)

COMPONENTES = {'R1': 1e3, 'C1': 10e-9, 'R2': 1e3, 'C2': 10e-9}
GBW_MAX4466_HZ = 200e3
GANANCIAS_MICROFONO = (25, 50, 125)  # rango del potenciómetro del módulo


def respuesta(f, c):
    s = 2j * np.pi * np.asarray(f, dtype=float)
    a2 = c['R1'] * c['C1'] * c['R2'] * c['C2']
    a1 = c['R1'] * c['C1'] + c['R2'] * c['C2'] + c['R1'] * c['C2']
    return 1 / (a2 * s ** 2 + a1 * s + 1)


def main():
    c = COMPONENTES
    f = np.logspace(1, 6, 4000)
    db = 20 * np.log10(np.abs(respuesta(f, c)))
    f_3db = float(f[np.argmax(db < -3)])
    db_en = lambda x: float(20 * np.log10(abs(respuesta(x, c))))
    pico_max = min(DC_MICROFONO - RANGO_ADC_V[0], RANGO_ADC_V[1] - DC_MICROFONO)
    # Aliasing: una componente en f > fs/2 aparece en |f - k fs|; se lista dónde cae y cuánto se atenúa.
    alias = {f'{x} Hz -> {abs(x - FS * round(x / FS))} Hz': db_en(x) for x in (9000, 10000, 12000, 13500, 15000, 20000)}
    # Con el micrófono: un polo en GBW/G en cascada con el RC.
    total = lambda x, g: float(20 * np.log10(abs(respuesta(x, c) / (1 + 1j * np.asarray(x) * g / GBW_MAX4466_HZ))))
    con_microfono = {f'ganancia {g}x (polo en {GBW_MAX4466_HZ / g / 1000:.1f} kHz)': {
        f'{x} Hz': total(x, g) for x in (440, 1320, 2500, F_RUIDO_MAX, 12000)} for g in GANANCIAS_MICROFONO}
    resultado = {
        'componentes': c, 'f_3db_hz': f_3db,
        'atenuacion_db': {**{f'{x} Hz (útil)': db_en(x) for x in TONOS_UTILES},
                          **{f'{x} Hz (interferencia)': db_en(x) for x in INTERFERENCIAS},
                          f'{F_RUIDO_MAX} Hz (ruido de banda)': db_en(F_RUIDO_MAX), 'Nyquist 8000 Hz': db_en(FS / 2)},
        'alias_atenuacion_db': alias,
        'rc_mas_microfono_db': con_microfono,
        'dc_en_adc_v': DC_MICROFONO, 'rango_adc_v': RANGO_ADC_V,
        'pico_maximo_microfono_v': pico_max, 'pico_maximo_codigos_aprox': pico_max * 1000 / MV_POR_CODIGO,
        'nota_rango': 'Con 1.65 V de DC la cota la pone el lado alto (2.45 V): pico <= 0.8 V. '
                      'Ajustar la ganancia del MAX4466 para que "adc" muestre max_mv < 2450 y min_mv > 150.'}
    for k, v in resultado.items():
        print(f'{k}: {v}')

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.semilogx(f, db, label='solo RC')
    for g in GANANCIAS_MICROFONO:
        ax.semilogx(f, db - 10 * np.log10(1 + (f * g / GBW_MAX4466_HZ) ** 2), lw=.8, label=f'RC + MAX4466 a {g}x')
    ax.legend(fontsize=8, loc='lower left')
    for x, nombre in ((max(TONOS_UTILES), 'útil'), (INTERFERENCIAS[0], 'interferencia'), (FS / 2, 'Nyquist'),
                      (f_3db, '-3 dB')):
        ax.axvline(x, ls='--', lw=.8, color='gray')
        ax.text(x, -38, nombre, rotation=90, va='bottom', ha='right', fontsize=8)
    ax.set(xlabel='Frecuencia (Hz)', ylabel='|H| (dB)', ylim=(-40, 3), xlim=(10, 1e5),
           title='Anti-aliasing: RC de dos etapas y ancho de banda del MAX4466')
    ax.grid(True, which='both', alpha=.3)
    salida = NODO1 / 'resultados'
    salida.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(salida / 'circuito_entrada.png', dpi=150)
    (salida / 'circuito_entrada.json').write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Guardado en {salida}')


if __name__ == '__main__':
    main()
