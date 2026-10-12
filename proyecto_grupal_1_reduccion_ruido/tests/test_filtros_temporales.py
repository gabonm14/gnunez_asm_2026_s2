"""Verifica especificaciones y ecuación propia con diferentes bloques."""
import json
import unittest
import numpy as np
from scipy.signal import lfilter
from src.generacion import RAIZ
from src.filtros_temporales import disenar_fir, filtrar_por_bloques

SPEC = json.loads((RAIZ / 'metadatos/filtro_temporal.json').read_text(encoding='utf-8-sig'))


class PruebasFiltroTemporal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b, cls.diseno = disenar_fir(SPEC)

    def test_cumple_especificaciones(self):
        self.assertLessEqual(self.diseno['rizado_pico_a_pico_db'], SPEC['rizado_max_db'])
        self.assertGreaterEqual(self.diseno['atenuacion_rechazo_min_db'], SPEC['atenuacion_min_db'])
        np.testing.assert_allclose(self.b, self.b[::-1], atol=1e-14)
        self.assertAlmostEqual(np.sum(self.b),1.0,places=12)

    def test_impulso_es_coeficientes(self):
        x = np.zeros(2*len(self.b)); x[0]=1
        y = filtrar_por_bloques(x,self.b,17)
        np.testing.assert_allclose(y[:len(self.b)],self.b,atol=1e-14)
        np.testing.assert_allclose(y[len(self.b):],0,atol=1e-14)

    def test_bloques_no_cambian_salida(self):
        x = np.random.default_rng(42).standard_normal(4099)
        referencia = lfilter(self.b,[1.0],x)
        for bloque in (1,17,1024,4099):
            with self.subTest(bloque=bloque):
                y = filtrar_por_bloques(x,self.b,bloque)
                np.testing.assert_allclose(y,referencia,atol=SPEC['tolerancia_atol'],rtol=SPEC['tolerancia_rtol'])

    def test_linealidad_y_retardo_tono(self):
        N = 4096; fs=SPEC['fs_hz']; f=1000
        n=np.arange(N)
        x=np.cos(2*np.pi*f*n/fs)
        y=filtrar_por_bloques(x,self.b)
        D=self.diseno['retardo_muestras']; M=self.diseno['orden']
        # Ganancia conocida por la DTFT de los coeficientes.
        ganancia=abs(np.sum(self.b*np.exp(-2j*np.pi*f*np.arange(len(self.b))/fs)))
        np.testing.assert_allclose(y[M+D:],ganancia*x[M:N-D],atol=1e-11)
        r=np.random.default_rng(43).standard_normal(N)
        np.testing.assert_allclose(filtrar_por_bloques(x+r,self.b),
                                   filtrar_por_bloques(x,self.b)+filtrar_por_bloques(r,self.b),atol=1e-12)


if __name__ == '__main__':
    unittest.main()
