"""Verifica el diagnóstico con señales sintéticas de respuesta conocida."""
import unittest
import numpy as np
from src.diagnostico import (cargar_config, psd_promediada, regiones_ocupadas, medir_impulsividad,
                             diagnosticar, adaptar_config_espectral)
from src.filtrado_espectral import validar_config
from src.generacion import RAIZ
import json

CFG = cargar_config()
BASE = json.loads((RAIZ / 'metadatos/filtro_espectral.json').read_text(encoding='utf-8-sig'))
FS, N = 16000, 1024
T = np.arange(4 * FS) / FS


def tonos(frecuencias, amplitudes):
    return sum(a * np.sin(2 * np.pi * f * T) for f, a in zip(frecuencias, amplitudes))


UTIL = tonos([440, 880, 1320], [1.0, .55, .3])


class PruebasDiagnostico(unittest.TestCase):
    def test_regiones_fusionan_huecos_pequenos(self):
        m = np.zeros(40, bool)
        m[[3, 4, 7, 20, 21]] = True
        self.assertEqual(regiones_ocupadas(m, 2), [(3, 7), (20, 21)])
        self.assertEqual(regiones_ocupadas(m, 0), [(3, 4), (7, 7), (20, 21)])
        self.assertEqual(regiones_ocupadas(np.zeros(5, bool), 2), [])

    def test_psd_valida_entrada(self):
        with self.assertRaises(ValueError):
            psd_promediada(np.zeros(100), 1000)
        with self.assertRaises(ValueError):
            psd_promediada(np.zeros(10), 1024)

    def test_sin_ruido_no_hay_interferencia(self):
        d = diagnosticar(UTIL, FS, N, CFG)
        self.assertEqual(d['tipo'], 'ninguno')
        self.assertEqual(d['confianza'], 'alta')
        self.assertAlmostEqual(d['fin_banda_util_hz'], 1320 + CFG['margen_banda_util_hz'], delta=60)

    def test_tono_interferente_frecuencia_y_banda_util(self):
        for f in (2508.0, 3333.0, 5200.0):
            with self.subTest(f=f):
                d = diagnosticar(UTIL + tonos([f], [.5]), FS, N, CFG)
                self.assertEqual(d['tipo'], 'tonal')
                self.assertAlmostEqual(d['frecuencias_interferentes_hz'][0], f, delta=3)
                self.assertAlmostEqual(d['fin_banda_util_hz'], 1320 + CFG['margen_banda_util_hz'], delta=60)

    def test_ruido_de_banda_separado(self):
        rng = np.random.default_rng(1)
        X = np.fft.rfft(rng.standard_normal(len(T)))
        f = np.fft.rfftfreq(len(T), 1 / FS)
        X[(f < 2500) | (f > 3800)] = 0
        ruido = np.fft.irfft(X, len(T))
        ruido *= 0.4 / ruido.std()
        d = diagnosticar(UTIL + ruido, FS, N, CFG)
        self.assertEqual(d['tipo'], 'banda')
        self.assertAlmostEqual(d['banda_ruido_hz'][0], 2500, delta=250)
        self.assertAlmostEqual(d['banda_ruido_hz'][1], 3800, delta=250)
        self.assertEqual(d['confianza'], 'alta')

    def test_red_electrica_se_excluye_de_la_banda_util(self):
        for f0 in (50.0, 60.0):
            with self.subTest(f0=f0):
                red = sum(np.sin(2 * np.pi * k * f0 * T + k) / k for k in range(1, 6))
                d = diagnosticar(UTIL + .4 * red, FS, N, CFG)
                self.assertIn('red_electrica', d['tipos'])
                self.assertEqual(d['frecuencia_red_hz'], f0)
                # Sin excluir los armónicos, la banda útil arrancaría en ~50 Hz y no cambiaría el borde,
                # pero el bloque útil debe empezar en la primera señal real (440 Hz).
                self.assertGreater(d['bloque_util_hz'][0], 300)

    def test_impulsos_detectados_y_confianza_baja(self):
        rng = np.random.default_rng(2)
        x = UTIL.copy()
        pos = rng.choice(len(T), 40, replace=False)
        x[pos] += rng.choice([-1, 1], 40) * 6
        d = diagnosticar(x, FS, N, CFG)
        self.assertIn('impulsivo', d['tipos'])
        self.assertEqual(d['confianza'], 'baja')
        self.assertAlmostEqual(d['impulsos_por_s_estimados'], 40 / 4, delta=1.5)
        c, _ = medir_impulsividad(UTIL + .2 * rng.standard_normal(len(T)), FS, CFG['k_atipicas_mad'])
        self.assertLess(c, CFG['umbral_curtosis'])

    def test_ruido_superpuesto_declara_confianza_baja(self):
        rng = np.random.default_rng(3)
        X = np.fft.rfft(rng.standard_normal(len(T)))
        f = np.fft.rfftfreq(len(T), 1 / FS)
        X[(f < 1000) | (f > 1800)] = 0
        ruido = np.fft.irfft(X, len(T))
        d = diagnosticar(UTIL + .5 * ruido / ruido.std(), FS, N, CFG)
        self.assertTrue(d['solapamiento'])
        self.assertEqual(d['confianza'], 'baja')

    def test_adaptador_respeta_restricciones_del_nodo_espectral(self):
        for f in (2508.0, 5200.0):
            d = diagnosticar(UTIL + tonos([f], [.5]), FS, N, CFG)
            nueva, usa = adaptar_config_espectral(d, BASE, FS)
            self.assertTrue(usa)
            validar_config(nueva)
            self.assertLess(nueva['fin_banda_util_hz'], nueva['inicio_rechazo_hz'])
        impulsivo = {'confianza': 'baja', 'fin_banda_util_hz': None}
        self.assertEqual(adaptar_config_espectral(impulsivo, BASE, FS), (BASE, False))

    def test_extiende_la_banda_util_si_la_senal_esta_por_encima_de_la_banda_fija(self):
        alta = tonos([1800, 2600, 3200], [1, .6, .4]) + tonos([5200], [.5])
        d = diagnosticar(alta, FS, N, CFG)
        nueva, usa = adaptar_config_espectral(d, BASE, FS)
        self.assertTrue(usa)
        self.assertGreater(nueva['fin_banda_util_hz'], 3200)
        self.assertLess(nueva['inicio_rechazo_hz'], 8000)


if __name__ == '__main__':
    unittest.main()
