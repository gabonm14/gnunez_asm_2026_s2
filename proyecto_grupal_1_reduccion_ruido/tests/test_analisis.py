"""Comprobaciones de escala, fase, Parseval y DFT frente a FFT."""
import unittest
import numpy as np
from src.analisis import dft_directa, espectro_bloque, energia_por_bandas, error_simetria


class PruebasAnalisis(unittest.TestCase):
    def test_dft_fft_compleja(self):
        rng = np.random.default_rng(25)
        x = rng.standard_normal(32) + 1j * rng.standard_normal(32)
        np.testing.assert_allclose(dft_directa(x), np.fft.fft(x), atol=1e-11, rtol=1e-11)

    def test_amplitud_y_fase_tono(self):
        N, k, amplitud, fase = 1024, 64, .7, .4
        x = amplitud * np.cos(2 * np.pi * k * np.arange(N) / N + fase)
        for ventana in ('boxcar', 'hann'):
            e = espectro_bloque(x, 16000, ventana)
            self.assertAlmostEqual(e['amplitud'][k], amplitud, places=12)
            self.assertAlmostEqual(e['fase_rad'][k], fase, places=12)

    def test_dc_y_nyquist_sin_duplicar(self):
        N = 128
        for x, bin_frecuencia in [(np.full(N, .3), 0), (.3 * (-1.) ** np.arange(N), N // 2)]:
            e = espectro_bloque(x, 16000, 'boxcar')
            self.assertAlmostEqual(e['amplitud'][bin_frecuencia], .3, places=12)

    def test_parseval_longitud_par_e_impar(self):
        rng = np.random.default_rng(26)
        for N in (127, 128):
            x = rng.standard_normal(N)
            bandas = energia_por_bandas(x, 16000, [0, 1500, 2300, 4000, 8000])
            np.testing.assert_allclose(sum(b['energia'] for b in bandas), np.sum(x * x), rtol=1e-12)
            self.assertAlmostEqual(sum(b['porcentaje'] for b in bandas), 100, places=10)

    def test_fase_nula_oculta_y_simetria(self):
        e = espectro_bloque(np.zeros(128), 16000)
        self.assertTrue(np.all(np.isnan(e['fase_rad'])))
        x = np.random.default_rng(27).standard_normal(1024)
        self.assertLess(error_simetria(x), 1e-10)


if __name__ == '__main__':
    unittest.main()
