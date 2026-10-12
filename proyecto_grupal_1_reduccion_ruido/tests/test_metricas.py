"""Resultados analíticos conocidos para comprobar la evaluación final."""
import unittest
import numpy as np
from src.metricas import intervalo_comun, medir_calidad, amplitud_componente, frecuencia_dominante


class PruebasMetricas(unittest.TestCase):
    def setUp(self):
        self.fs=16000;self.n=np.arange(16000)
        self.s=np.sin(2*np.pi*1000*self.n/self.fs)
        self.r=.5*np.cos(2*np.pi*2500*self.n/self.fs)

    def test_ruido_reducido_a_la_mitad_mejora_seis_db(self):
        m=medir_calidad(self.s,self.s+self.r,self.s+.5*self.r,self.s,.5*self.r,self.fs,2500)
        self.assertAlmostEqual(m['mejora_snr_db'],20*np.log10(2),places=10)
        self.assertAlmostEqual(m['atenuacion_componente_dominante_db'],20*np.log10(2),places=10)
        self.assertAlmostEqual(m['mse'],.03125,places=10)
        self.assertAlmostEqual(m['energia_util_conservada_pct'],100,places=10)

    def test_energia_util_no_es_energia_total(self):
        ys=.5*self.s;yr=self.r
        m=medir_calidad(self.s,self.s+self.r,ys+yr,ys,yr,self.fs,2500)
        self.assertAlmostEqual(m['energia_util_conservada_pct'],25,places=10)
        self.assertAlmostEqual(m['distorsion_util_mse'],.125,places=10)

    def test_intervalo_alinea_retardo(self):
        D=40;inicio,fin=intervalo_comun(len(self.s),1024,80,D)
        retrasada=np.concatenate([np.zeros(D),self.s])[:len(self.s)]
        np.testing.assert_array_equal(retrasada[inicio+D:fin+D],self.s[inicio:fin])

    def test_frecuencia_y_amplitud_conocidas(self):
        self.assertAlmostEqual(frecuencia_dominante(self.r,self.fs),2500,places=8)
        self.assertAlmostEqual(amplitud_componente(self.r,self.fs,2500),.5,places=12)

    def test_rechaza_longitudes_distintas(self):
        with self.assertRaises(ValueError):
            medir_calidad(self.s,self.s+self.r,self.s[:-1],self.s,self.r,self.fs,2500)


if __name__=='__main__':
    unittest.main()
