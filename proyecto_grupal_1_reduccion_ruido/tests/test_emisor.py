"""Verifica cuantización, divisor del LEDC y la cadena PWM + RC."""
import copy
import unittest
import numpy as np
from src.emisor import (cargar_config, cuantizar, sqnr_teorica_db, razon_duty, divisor_ledc,
                        respuesta_rc, rc_discreto, simular_pwm_rc, emitir, retardo_grupo_dc_s)

CFG, SPEC = cargar_config()
FS = SPEC['fs_hz']


class PruebasEmisor(unittest.TestCase):
    def test_cuantizacion_cubre_rango_y_error_acotado(self):
        x = np.linspace(-1, 1, 10001)
        codigo, rec = cuantizar(x, 8)
        self.assertEqual((codigo.min(), codigo.max()), (0, 255))
        self.assertLessEqual(np.max(abs(rec - x)), 1 / 255 + 1e-12)
        _, saturada = cuantizar(np.array([-3.0, 3.0]), 8)
        np.testing.assert_allclose(saturada, [-1, 1])

    def test_sqnr_cercana_a_la_teorica_de_escala_completa(self):
        x = np.sin(2 * np.pi * np.arange(100000) * 0.01234)
        _, rec = cuantizar(x, 8)
        medida = 10 * np.log10(np.mean(x ** 2) / np.mean((rec - x) ** 2))
        self.assertAlmostEqual(medida, 6.02 * 8 + 1.76, delta=CFG['tolerancia_sqnr_db'])
        self.assertAlmostEqual(medida, sqnr_teorica_db(x, 8), delta=1.0)

    def test_divisor_ledc(self):
        d = divisor_ledc(CFG, FS)
        self.assertGreaterEqual(d['divisor_ledc'], 1)
        self.assertLess(abs(d['desajuste_pct']), 1)
        self.assertLessEqual(d['f_pwm_real_hz'], d['f_pwm_max_hz'])
        otro = copy.deepcopy(CFG)
        otro['osr_pwm'] = 64  # 1.024 MHz > 312.5 kHz
        with self.assertRaises(ValueError):
            divisor_ledc(otro, FS)

    def test_rc_discreto_ganancia_dc_unitaria_y_coincide_con_analogico(self):
        b, a, fsim = rc_discreto(CFG, FS)
        self.assertAlmostEqual(np.sum(b) / np.sum(a), 1.0, places=9)
        f = np.array([500.0, 1500.0, 2300.0])
        z = np.exp(-2j * np.pi * f / fsim)
        Hz = np.polyval(b[::-1], z) / np.polyval(a[::-1], z)
        np.testing.assert_allclose(abs(Hz), abs(respuesta_rc(CFG, f)), rtol=1e-3)

    def test_duty_constante_da_nivel_medio_proporcional(self):
        for razon in (0.25, 0.5, 0.75):
            y, rizado = simular_pwm_rc(np.full(400, razon), CFG, FS)
            # Se muestrea en un instante fijo del periodo PWM; con duty distinto de 50 %
            # el rizado es asimétrico, así que el error está acotado por el rizado completo.
            self.assertAlmostEqual(y[-1], razon * CFG['vdd_v'], delta=rizado[-1] + 1e-4)

    def test_rizado_cae_con_el_orden_del_rc(self):
        uno, dos = copy.deepcopy(CFG), copy.deepcopy(CFG)
        uno['orden_rc'], dos['orden_rc'] = 1, 2
        _, r1 = simular_pwm_rc(np.full(300, 0.5), uno, FS)
        _, r2 = simular_pwm_rc(np.full(300, 0.5), dos, FS)
        self.assertLess(r2[-100:].max(), r1[-100:].max())

    def test_rizado_de_primer_orden_coincide_con_la_formula(self):
        # Triángulo con duty 50 %: pico a pico = Vdd / (4 f_pwm RC) para f_pwm*RC >> 1.
        uno = copy.deepcopy(CFG)
        uno['orden_rc'] = 1
        _, r = simular_pwm_rc(np.full(300, 0.5), uno, FS)
        esperado = uno['vdd_v'] / (4 * FS * uno['osr_pwm'] * uno['R1_ohm'] * uno['C1_nf'] * 1e-9)
        self.assertAlmostEqual(r[-1] / esperado, 1.0, delta=0.1)

    def test_cadena_reproduce_tono_con_retardo_del_rc(self):
        n = 3000
        f = 440.0
        x = 0.8 * np.sin(2 * np.pi * f * np.arange(n) / FS)
        e = emitir(x, CFG, FS)
        y = e['salida_v'] - e['salida_v'].mean()
        H = respuesta_rc(CFG, [f])[0]
        esperado = CFG['vdd_v'] * 255 / 256 / 2 * 0.8 * abs(H)
        # La amplitud sale de un ajuste por mínimos cuadrados sobre el régimen permanente.
        t = np.arange(n)[500:] / FS
        base = np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)])
        coef = np.linalg.lstsq(base, y[500:], rcond=None)[0]
        self.assertAlmostEqual(np.hypot(*coef), esperado, delta=0.02 * esperado)
        self.assertAlmostEqual(-np.angle(H) / (2 * np.pi * f), retardo_grupo_dc_s(CFG), delta=3e-6)


if __name__ == '__main__':
    unittest.main()
