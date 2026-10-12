"""Pruebas de WOLA, simetría, estado adaptativo y máscaras de evaluación."""
import json
import unittest
import numpy as np
from src.generacion import RAIZ
from src.filtrado_espectral import reducir_espectral, EstimadorEspectral, validar_config

CONFIG=json.loads((RAIZ/'metadatos/filtro_espectral.json').read_text(encoding='utf-8-sig'))


class PruebasEspectral(unittest.TestCase):
    def test_identidad_incluye_bordes_y_longitudes_arbitrarias(self):
        rng=np.random.default_rng(50)
        for L in (1,257,1024,11111):
            with self.subTest(longitud=L):
                x=rng.standard_normal(L)
                p=reducir_espectral(x,CONFIG,reduccion=False)
                self.assertEqual(len(p['salida']),L)
                self.assertGreater(p['pesos_min'],0)
                np.testing.assert_allclose(p['salida'],x,atol=1e-12,rtol=1e-12)

    def test_ganancias_conservan_simetria(self):
        N=CONFIG['n_bloque']
        x=np.random.default_rng(51).standard_normal(N)
        X=np.fft.rfft(x)
        G=EstimadorEspectral(CONFIG).estimar_ganancia(X)
        Y=X*G
        completo=np.concatenate([Y,np.conj(Y[-2:0:-1])])
        self.assertEqual(len(completo),N)
        self.assertLess(np.max(abs(np.fft.ifft(completo).imag)),1e-12)
        self.assertTrue(np.all((G>=0)&(G<=1)))

    def test_estimacion_se_actualiza_y_es_determinista(self):
        X=np.fft.rfft(np.random.default_rng(52).standard_normal(CONFIG['n_bloque']))
        e=EstimadorEspectral(CONFIG);otro=EstimadorEspectral(CONFIG)
        g=e.estimar_ganancia(X)
        np.testing.assert_array_equal(g,otro.estimar_ganancia(X))
        anterior=e.ruido_estimado.copy()
        e.estimar_ganancia(10*X)
        self.assertTrue(np.all(e.ruido_estimado>anterior))

    def test_mascara_congelada_preserva_descomposicion(self):
        rng=np.random.default_rng(53)
        s=rng.standard_normal(4099);r=rng.standard_normal(4099)
        p=reducir_espectral(s+r,CONFIG)
        ys=reducir_espectral(s,CONFIG,ganancias=p['ganancias'])['salida']
        yr=reducir_espectral(r,CONFIG,ganancias=p['ganancias'])['salida']
        np.testing.assert_allclose(ys+yr,p['salida'],atol=1e-12)

    def test_silencio_sin_nan(self):
        p=reducir_espectral(np.zeros(4099),CONFIG)
        self.assertTrue(np.all(np.isfinite(p['salida'])))
        np.testing.assert_array_equal(p['salida'],np.zeros(4099))

    def test_rechaza_bloque_no_potencia_de_dos(self):
        with self.assertRaises(ValueError):
            validar_config({**CONFIG,'n_bloque':1000})


if __name__=='__main__':
    unittest.main()
