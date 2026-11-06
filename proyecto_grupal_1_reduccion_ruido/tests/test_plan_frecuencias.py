"""Pruebas del plan de frecuencias: cálculos analíticos y prototipo de máscara."""
import copy
import unittest
import numpy as np
from src.plan_frecuencias import (cargar_configuraciones, verificar_coherencia, n_minimo, n_maximo,
                                  tabla_componentes, verificar_plan, mascara_por_picos,
                                  evaluar_mascara, senal_util, amplitud_interferencia)

CFG = cargar_configuraciones()
CONFIG = CFG['configuraciones']
PLAN = CFG['plan_frecuencias']


class PruebasPlanFrecuencias(unittest.TestCase):
    def test_configuraciones_actuales_son_coherentes(self):
        verificar_coherencia(CFG)
        verificar_plan(CONFIG, PLAN, tabla_componentes(CONFIG, PLAN['separacion_minima_hz']))

    def test_rechaza_fs_distinta_entre_json(self):
        cfg = copy.deepcopy(CFG)
        cfg['filtro_espectral']['fs_hz'] = 8000
        with self.assertRaises(ValueError):
            verificar_coherencia(cfg)

    def test_n_minimo_y_maximo(self):
        self.assertEqual(n_minimo(62.5, 16000), 1024)
        self.assertEqual(n_minimo(100, 16000), 1024)
        self.assertEqual(n_minimo(125, 16000), 512)
        self.assertEqual(n_maximo(64, 16000), 1024)
        self.assertEqual(n_maximo(63, 16000), 512)

    def test_bins_dentro_y_fuera(self):
        tabla = tabla_componentes(CONFIG, PLAN['separacion_minima_hz'])
        por_frecuencia = {(c['origen'], c['f_min_hz']): c for c in tabla}
        self.assertTrue(por_frecuencia[('caso_1', 2500)]['en_bin'])
        self.assertAlmostEqual(por_frecuencia[('util', 440)]['fraccion_bin'], 0.16)
        self.assertEqual(por_frecuencia[('caso_3', 1000)]['zona'], 'compromiso')

    def test_rechaza_tonos_utiles_inseparables(self):
        config = {**CONFIG, 'frecuencias_utiles_hz': [440, 470, 1320]}
        with self.assertRaises(ValueError):
            verificar_plan(config, PLAN, tabla_componentes(config, PLAN['separacion_minima_hz']))

    def test_rechaza_n_que_no_cumple_requisitos(self):
        for n in (512, 2048):
            config = {**CONFIG, 'n_bloque': n}
            with self.subTest(n_bloque=n), self.assertRaises(ValueError):
                verificar_plan(config, PLAN, tabla_componentes(config, PLAN['separacion_minima_hz']))

    def test_mascara_sin_interferencia_reconstruye(self):
        t = np.arange(16000) / CONFIG['fs_hz']
        s = senal_util(CONFIG, t)
        y, _ = mascara_por_picos(s, 1024, CONFIG['fs_hz'], CONFIG['frecuencias_utiles_hz'], 20, 1)
        np.testing.assert_allclose(y, s, atol=1e-10)

    def test_separada_se_elimina_y_pegada_no(self):
        fs = CONFIG['fs_hz']
        t = np.arange(16000) / fs
        s = senal_util(CONFIG, t)
        a = amplitud_interferencia(s, 2.0)
        lejos = evaluar_mascara(s, a * np.sin(2 * np.pi * 1080 * t), 1024, fs,
                                CONFIG['frecuencias_utiles_hz'], PLAN['barrido_separacion'])
        cerca = evaluar_mascara(s, a * np.sin(2 * np.pi * 885 * t), 1024, fs,
                                CONFIG['frecuencias_utiles_hz'], PLAN['barrido_separacion'])
        self.assertGreater(lejos['mejora_snr_db'], 20)
        self.assertGreater(lejos['energia_util_conservada_pct'], 99)
        self.assertLess(cerca['mejora_snr_db'], 1)


if __name__ == '__main__':
    unittest.main()
