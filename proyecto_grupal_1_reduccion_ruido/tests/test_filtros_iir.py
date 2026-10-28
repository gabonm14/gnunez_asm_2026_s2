"""Verifica diseño IIR, estabilidad y que la ecuación propia coincida con SciPy."""
import unittest
import numpy as np
from scipy.signal import sosfilt, sosfreqz, sos2zpk
from src.filtros_iir import (cargar_specs, disenar_iir, filtrar_sos_por_bloques,
                             cuantizar_coef, medir_respuesta_sos, retardo_efectivo)

SPEC, CFG = cargar_specs()


class PruebasFiltroIIR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.disenos = {f: disenar_iir(SPEC, CFG, f) for f in CFG['familias']}

    def test_cumple_especificaciones_y_es_estable(self):
        for familia, (sos, res) in self.disenos.items():
            with self.subTest(familia=familia):
                self.assertLessEqual(res['rizado_pico_a_pico_db'], SPEC['rizado_max_db'])
                self.assertGreaterEqual(res['atenuacion_rechazo_min_db'], SPEC['atenuacion_min_db'])
                self.assertLess(max(abs(sos2zpk(sos)[1])), 1)
                self.assertTrue(res['estable_bibo'])
                self.assertEqual(len(sos) , (res['orden'] + 1) // 2)

    def test_chebyshev_necesita_menor_orden(self):
        self.assertLess(self.disenos['chebyshev1'][1]['orden'], self.disenos['butterworth'][1]['orden'])

    def test_bloques_no_cambian_salida(self):
        x = np.random.default_rng(42).standard_normal(4099)
        for familia, (sos, _) in self.disenos.items():
            referencia = sosfilt(sos, x)
            for bloque in (1, 17, 1024, 4099):
                with self.subTest(familia=familia, bloque=bloque):
                    y = filtrar_sos_por_bloques(x, sos, bloque)
                    np.testing.assert_allclose(y, referencia, atol=CFG['tolerancia_atol'], rtol=CFG['tolerancia_rtol'])

    def test_ganancia_dc_y_linealidad(self):
        # Chebyshev tipo I de orden par tiene ganancia DC = -rizado, no 0 dB.
        for familia, (sos, res) in self.disenos.items():
            with self.subTest(familia=familia):
                y = filtrar_sos_por_bloques(np.ones(20000), sos)
                _, H = sosfreqz(sos, worN=[0.0])
                self.assertAlmostEqual(y[-1], abs(H[0]), places=6)
                self.assertGreater(20 * np.log10(y[-1]), -SPEC['rizado_max_db'])
                rng = np.random.default_rng(43)
                a, b = rng.standard_normal(2048), rng.standard_normal(2048)
                np.testing.assert_allclose(filtrar_sos_por_bloques(a + b, sos),
                                           filtrar_sos_por_bloques(a, sos) + filtrar_sos_por_bloques(b, sos), atol=1e-10)

    def test_cuantizacion_q214_mantiene_estabilidad(self):
        for familia, (sos, _) in self.disenos.items():
            with self.subTest(familia=familia):
                sos_q, saturados = cuantizar_coef(sos, CFG['bits_fraccion_coef'])
                self.assertEqual(saturados, 0)
                self.assertLess(max(abs(sos2zpk(sos_q)[1])), 1)

    def test_retardo_efectivo_recupera_retardo_conocido(self):
        s = np.random.default_rng(5).standard_normal(3000)
        ys = np.concatenate([np.zeros(12), s[:-12]])
        self.assertEqual(retardo_efectivo(s, ys, 50, 40), 12)


if __name__ == '__main__':
    unittest.main()
