"""Pruebas del banco de señales; ejecutables con unittest o pytest."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from src.generacion import RAIZ, generar_caso, exportar_caso, validar_configuracion, snr_db

CONFIG = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))


class PruebasGeneracion(unittest.TestCase):
    def test_casos_reproducibles_snr_y_archivos(self):
        validar_configuracion(CONFIG)
        for caso in CONFIG['casos']:
            with self.subTest(caso=caso['id']):
                datos = generar_caso(CONFIG, caso)
                repeticion = generar_caso(CONFIG, caso)
                for nombre in ('limpia', 'ruido', 'contaminada'):
                    np.testing.assert_array_equal(datos[nombre], repeticion[nombre])
                    self.assertLessEqual(np.max(np.abs(datos[nombre])), CONFIG['pico_maximo'] + 1e-12)
                np.testing.assert_allclose(datos['limpia'] + datos['ruido'], datos['contaminada'], atol=1e-14)
                self.assertAlmostEqual(snr_db(datos['limpia'], datos['contaminada']), caso['snr_objetivo_db'], places=10)
                with tempfile.TemporaryDirectory() as carpeta:
                    exportar_caso(datos, carpeta)
                    with np.load(Path(carpeta) / 'muestras.npz') as archivo:
                        for nombre in ('limpia', 'ruido', 'contaminada'):
                            np.testing.assert_array_equal(archivo[nombre], datos[nombre])
                    fs, limpia = wavfile.read(Path(carpeta) / 'limpia.wav')
                    _, mezcla = wavfile.read(Path(carpeta) / 'contaminada.wav')
                    self.assertEqual(fs, CONFIG['fs_hz'])
                    self.assertEqual(limpia.dtype, np.int16)
                    self.assertEqual(len(limpia), int(CONFIG['fs_hz'] * CONFIG['duracion_s']))
                    self.assertLess(abs(snr_db(limpia.astype(float), mezcla.astype(float)) - caso['snr_objetivo_db']), 0.01)

    def test_semilla_distinta_cambia_ruido(self):
        caso = CONFIG['casos'][1]
        a = generar_caso(CONFIG, caso)
        b = generar_caso(CONFIG, {**caso, 'semilla': caso['semilla'] + 100})
        self.assertFalse(np.array_equal(a['ruido'], b['ruido']))

    def test_rechaza_nyquist(self):
        config = {**CONFIG, 'frecuencias_utiles_hz': [440, 880, CONFIG['fs_hz'] / 2]}
        with self.assertRaises(ValueError):
            validar_configuracion(config)


if __name__ == '__main__':
    unittest.main()
