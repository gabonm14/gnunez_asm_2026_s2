"""Verifica el orquestador end-to-end con registros cortos."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from src.generacion import RAIZ, generar_caso
from src.pipeline import cargar_configuraciones, correr_pipeline, nodo_adquisicion

CONFIG = json.loads((RAIZ / 'metadatos/configuraciones.json').read_text(encoding='utf-8-sig'))
CORTA = {**CONFIG, 'duracion_s': 2.0}
TONAL = {'semilla': 7, 'tipo_ruido': 'tonal', 'frecuencia_interferencia_hz': 2500, 'snr_objetivo_db': 2.0}


def ruta_pipeline(**cambios):
    cfg = json.loads((RAIZ / 'metadatos/pipeline.json').read_text(encoding='utf-8-sig'))
    cfg.update(cambios)
    carpeta = tempfile.mkdtemp()
    ruta = Path(carpeta) / 'pipeline.json'
    ruta.write_text(json.dumps(cfg), encoding='utf-8')
    return str(ruta)


class PruebasPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        casos = {'tonal': generar_caso(CORTA, TONAL)}
        cls.res = correr_pipeline(ruta_pipeline(metodos=['FIR', 'IIR', 'espectral_adaptativo']),
                                  casos=casos, guardar=False)

    def test_reporta_todos_los_metodos_y_la_referencia(self):
        metodos = [f['metodo'] for f in self.res['metricas']]
        self.assertEqual(metodos, ['sin_filtrar', 'FIR', 'IIR', 'espectral_adaptativo'])
        base = self.res['metricas'][0]
        self.assertAlmostEqual(base['mejora_snr_db'], 0, places=9)
        self.assertAlmostEqual(base['mejora_snr_separada_db'], 0, places=9)

    def test_cada_metodo_reduce_el_ruido_de_un_tono_separado(self):
        for f in self.res['metricas'][1:]:
            with self.subTest(metodo=f['metodo']):
                self.assertGreater(f['mejora_snr_separada_db'], 20)
                self.assertGreater(f['energia_util_conservada_pct'], 95)
                self.assertEqual(f['muestras_fuera_rango_pcm'], 0)

    def test_compensaciones_y_latencias(self):
        por_metodo = {f['metodo']: f for f in self.res['metricas']}
        self.assertEqual(por_metodo['FIR']['compensacion_muestras'], 40)
        self.assertGreater(por_metodo['IIR']['compensacion_muestras'], 0)
        self.assertAlmostEqual(por_metodo['FIR']['latencia_algoritmica_ms'], 2.5)
        self.assertAlmostEqual(por_metodo['espectral_adaptativo']['latencia_algoritmica_ms'], 64.0)

    def test_nodo1_diagnostica_y_alimenta_al_nodo3(self):
        etapa = self.res['etapas'][0]
        self.assertEqual(etapa['nodo1_tipo_diagnosticado'], 'tonal')
        self.assertEqual(etapa['nodo1_confianza'], 'alta')
        self.assertEqual(etapa['nodo1_usa_diagnostico'], 1)
        self.assertAlmostEqual(etapa['snr_entrada_real_db'], 2.0, delta=0.5)
        json.dumps(self.res['diagnosticos'])  # serializable para guardarse

    def test_adquisicion_cuantiza_y_elimina_dc(self):
        cfg = cargar_configuraciones()
        v = 1.65 + .8 * np.sin(np.linspace(0, 40, 5000))
        x, info = nodo_adquisicion(v, 1.0, cfg, 16000)
        self.assertAlmostEqual(float(x.mean()), 0, places=9)
        self.assertLessEqual(np.max(np.abs((x + info['offset_dc_v']) - v)), info['paso_adc_v'] / 2 + 1e-12)
        _, info = nodo_adquisicion(np.array([-1.0, 1.0, 5.0]), 1.0, cfg, 16000)
        self.assertEqual(info['muestras_saturadas_adc'], 2)

    def test_rechaza_configuraciones_invalidas(self):
        with self.assertRaises(ValueError):
            cargar_configuraciones(ruta_pipeline(metodos=['FIR', 'inexistente']))
        with self.assertRaises(ValueError):
            correr_pipeline(ids=['no_existe'], guardar=False)


if __name__ == '__main__':
    unittest.main()
