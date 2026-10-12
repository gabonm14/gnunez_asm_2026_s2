"""Comparación final automática: entrada, FIR y FFT/IFFT.

Ejecutable directamente desde VS Code. Recalcula señales y salidas para
evitar comparar resultados antiguos producidos con configuraciones distintas.
"""
import json
import platform
import sys
from time import perf_counter
import numpy as np
import scipy
import matplotlib.pyplot as plt

if __package__ in (None,''):
    from generacion import RAIZ,generar_todos
    from analisis import guardar_csv,guardar_figura,espectro_bloque
    from filtros_temporales import disenar_fir,filtrar_por_bloques
    from filtrado_espectral import reducir_espectral
    from metricas import intervalo_comun,frecuencia_dominante,medir_calidad
else:
    from .generacion import RAIZ,generar_todos
    from .analisis import guardar_csv,guardar_figura,espectro_bloque
    from .filtros_temporales import disenar_fir,filtrar_por_bloques
    from .filtrado_espectral import reducir_espectral
    from .metricas import intervalo_comun,frecuencia_dominante,medir_calidad


def cargar_config(nombre):
    return json.loads((RAIZ/'metadatos'/nombre).read_text(encoding='utf-8-sig'))


def recursos(b,config,N):
    K=config['n_bloque']//2+1
    return {'sin_filtrar':0,
            'FIR':4*(len(b)+len(b)-1)+8*N,
            'espectral':4*(5*config['n_bloque']+4*K)+16*K}


def medir_tiempos(x,b,config,N,ajustes):
    """Tiempo amortizado por bloque/marco de la implementación Python.

    Incluye procesamiento y allocations del wrapper offline. Excluye diseño,
    figuras, métricas, archivos, ADC/DAC y comunicaciones. No mide firmware.
    P95 corresponde a las repeticiones, no a latencias de marcos individuales.
    """
    rep=ajustes['repeticiones_tiempo'];nb=ajustes['bloques_para_tiempo']
    if not isinstance(rep,int) or rep<3 or not isinstance(nb,int) or nb<2:
        raise ValueError('Use al menos 3 repeticiones y 2 bloques.')
    muestra=x[:min(len(x),nb*N)]
    resultado={}
    for metodo in ('FIR','espectral'):
        def ejecutar():
            if metodo=='FIR':
                filtrar_por_bloques(muestra,b,N)
                return int(np.ceil(len(muestra)/N))
            p=reducir_espectral(muestra,config)
            return len(p['inicios'])
        ejecutar()  # Calentamiento fuera de las mediciones.
        mediciones=[]
        for _ in range(rep):
            t0=perf_counter();cantidad=ejecutar()
            mediciones.append(1000*(perf_counter()-t0)/cantidad)
        resultado[metodo]={'tiempo_medio_bloque_mediana_ms':float(np.median(mediciones)),
            'tiempo_medio_bloque_p95_ms':float(np.percentile(mediciones,95)),
            'repeticiones':rep,'bloques_por_repeticion':cantidad,'muestras_por_repeticion':len(muestra)}
    return resultado


def verificar_criterios(fila,criterios):
    """Criterios explícitos del prototipo; el caso 3 puede fallar en FIR."""
    if fila['metodo']=='sin_filtrar':
        return 'referencia'
    superpuesto=fila['caso']=='caso_3'
    mejora=criterios['mejora_min_caso_superpuesto_db' if superpuesto else 'mejora_min_casos_separados_db']
    energia=criterios['energia_util_min_caso_superpuesto_pct' if superpuesto else 'energia_util_min_casos_separados_pct']
    cumple=(fila['mejora_snr_db']>=mejora and fila['energia_util_conservada_pct']>=energia and fila['muestras_fuera_rango_pcm']==0)
    return 'cumple' if cumple else 'no_cumple'


def ejecutar_comparacion(casos=None):
    spec=cargar_config('filtro_temporal.json')
    config=cargar_config('filtro_espectral.json')
    ajustes=cargar_config('comparacion.json')
    if spec['fs_hz']!=config['fs_hz']:
        raise ValueError('Ambos métodos deben usar el mismo muestreo.')
    b,diseno=disenar_fir(spec);D=diseno['retardo_muestras'];M=diseno['orden']
    casos=generar_todos() if casos is None else casos
    resultados=RAIZ/'resultados';figuras=resultados/'figuras'
    figuras.mkdir(parents=True,exist_ok=True)
    filas=[];intervalos={};salidas={};tiempos=[]
    for nombre,datos in casos.items():
        fs=datos['metadatos']['fs_hz'];N=datos['metadatos']['n_bloque']
        if fs!=spec['fs_hz'] or N!=config['n_bloque']:
            raise ValueError('Señales y filtros deben compartir fs y tamaño nominal de bloque.')
        s,r,x=datos['limpia'],datos['ruido'],datos['contaminada']
        inicio,fin=intervalo_comun(len(s),N,M,D)
        v=slice(inicio,fin);vf=slice(inicio+D,fin+D)
        yf=filtrar_por_bloques(x,b,N);ysf=filtrar_por_bloques(s,b,N);yrf=filtrar_por_bloques(r,b,N)
        pe=reducir_espectral(x,config);G=pe['ganancias'];ye=pe['salida']
        yse=reducir_espectral(s,config,ganancias=G)['salida']
        yre=reducir_espectral(r,config,ganancias=G)['salida']
        if not np.allclose(yf,ysf+yrf,atol=1e-12,rtol=1e-10) or not np.allclose(ye,yse+yre,atol=1e-12,rtol=1e-10):
            raise AssertionError('Las referencias de evaluación no reconstruyen la salida.')
        # Tonal: frecuencia física conocida por el evaluador. Banda: bin máximo de ruido aislado.
        fdom=(datos['metadatos']['frecuencia_interferencia_hz'] if datos['metadatos']['tipo_ruido']=='tonal'
              else frecuencia_dominante(r[v],fs))
        medicion_tiempo=medir_tiempos(x,b,config,N,ajustes)
        ram=recursos(b,config,N)
        alineadas={'sin_filtrar':(x[v],s[v],r[v]),'FIR':(yf[vf],ysf[vf],yrf[vf]),'espectral':(ye[v],yse[v],yre[v])}
        for metodo,(y,ys,yr) in alineadas.items():
            medidas=medir_calidad(s[v],x[v],y,ys,yr,fs,fdom)
            original=x if metodo=='sin_filtrar' else yf if metodo=='FIR' else ye
            tm=medicion_tiempo.get(metodo,{'tiempo_medio_bloque_mediana_ms':0.0,'tiempo_medio_bloque_p95_ms':0.0})
            periodo=1000*(config['salto'] if metodo=='espectral' else N)/fs
            fila={'caso':nombre,'metodo':metodo,**medidas,'inicio_referencia':inicio,'fin_referencia_exclusivo':fin,
                  'muestras_evaluadas':fin-inicio,'compensacion_fir_muestras':D if metodo=='FIR' else 0,
                  **{k:tm[k] for k in ('tiempo_medio_bloque_mediana_ms','tiempo_medio_bloque_p95_ms')},
                  'muestras_nuevas_por_actualizacion':config['salto'] if metodo=='espectral' else N,
                  'periodo_actualizacion_ms':periodo,'ram_base_embebida_bytes':ram[metodo],
                  'tiempo_amortizado_por_muestra_ns':tm['tiempo_medio_bloque_mediana_ms']*1e6/(config['salto'] if metodo=='espectral' else N),
                  'pico_salida_registro':float(max(abs(original))),
                  'muestras_fuera_rango_pcm':int(np.count_nonzero(abs(original)>1))}
            fila['criterio_calidad']=verificar_criterios(fila,ajustes['criterios_predefinidos'])
            filas.append(fila)
            if metodo!='sin_filtrar':
                tiempos.append({'caso':nombre,'metodo':metodo,**tm})
        intervalos[nombre]={'inicio':inicio,'fin_exclusivo':fin,'fir_inicio':inicio+D,'fir_fin_exclusivo':fin+D}
        salidas[nombre]={'FIR':yf,'espectral':ye}
        carpeta=resultados/'comparacion'/nombre;carpeta.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(carpeta/'salidas_alineadas.npz',tiempo=datos['tiempo'][v],limpia=s[v],entrada=x[v],
                            fir=yf[vf],espectral=ye[v],fir_limpia=ysf[vf],fir_ruido=yrf[vf],
                            espectral_limpia=yse[v],espectral_ruido=yre[v])
        fig,axs=plt.subplots(2,1,figsize=(12,7));L=min(int(.01*fs),fin-inicio)
        for etiqueta,y in [('Limpia',s[v]),('Entrada',x[v]),('FIR',yf[vf]),('Espectral',ye[v])]:
            axs[0].plot(datos['tiempo'][inicio:inicio+L]*1000,y[:L],label=etiqueta,alpha=.8)
            e=espectro_bloque(y[:N],fs)
            axs[1].plot(e['frecuencia_hz'],e['magnitud_db'],label=etiqueta)
        axs[0].set(xlabel='Tiempo de referencia (ms)',ylabel='Amplitud',title=f'{nombre}: mismo intervalo; FIR compensada {D} muestras')
        axs[1].set(xlabel='Frecuencia (Hz)',ylabel='Amplitud (dB re 1)',ylim=(-110,5))
        for ax in axs:ax.grid(True,alpha=.25);ax.legend()
        guardar_figura(fig,figuras/f'{nombre}_comparacion.png')
    guardar_csv(resultados/'metricas.csv',filas)
    guardar_csv(resultados/'tiempos_procesamiento.csv',tiempos)
    entorno={'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,
             'sistema':platform.platform(),'arquitectura':platform.machine(),'procesador':platform.processor()}
    auditoria={'config_temporal':spec,'config_espectral':config,'config_comparacion':ajustes,
               'entorno_medicion':entorno,'intervalos':intervalos,
               'nota_tiempo':'Mediana/P95 de tiempos amortizados por bloque en Python, con calentamiento. No mide latencia física ni firmware.',
               'nota_baseline':'Tiempo y RAM de sin_filtrar se fijan en cero como costo adicional de filtrado; adquisición y reproducción quedan fuera.',
               'nota_implementaciones':'FIR usa bucle de Python; FFT/IFFT usa biblioteca optimizada. Los tiempos no establecen superioridad intrínseca de los algoritmos ni anticipan tiempos de firmware.',
               'nota_memoria':'Estimación base float32/complex64 del diseño embebido. Excluye scratch FFT, pila, comunicaciones y máscaras históricas offline.',
               'nota_banda_ancha':'La frecuencia dominante es el máximo de un registro particular de ruido; su atenuación no representa toda la banda.',
               'nota_criterios':'Objetivos propuestos para este banco de prueba, no requisitos impuestos por el profesor; no ajustarlos para ocultar fallos.'}
    (resultados/'comparacion_metadatos.json').write_text(json.dumps(auditoria,indent=2,ensure_ascii=False),encoding='utf-8')
    fig,axs=plt.subplots(1,2,figsize=(12,5));pos=np.arange(len(casos))
    for j,metodo in enumerate(('sin_filtrar','FIR','espectral')):
        grupo=[f for f in filas if f['metodo']==metodo]
        axs[0].bar(pos+(j-1)*.25,[f['snr_salida_db'] for f in grupo],width=.25,label=metodo)
        axs[1].bar(pos+(j-1)*.25,[f['mse'] for f in grupo],width=.25,label=metodo)
    axs[0].set(ylabel='SNR de salida (dB)',title='Calidad en el intervalo común')
    axs[1].set(ylabel='MSE',yscale='log',title='Error respecto a la señal limpia')
    for ax in axs:ax.set_xticks(pos,list(casos));ax.grid(True,axis='y',alpha=.25);ax.legend()
    guardar_figura(fig,figuras/'comparacion_metricas.png')
    lineas=['# Comparación automática\n','Mismo intervalo de referencia para entrada, FIR y espectral.\n',
            '| Caso | Método | MSE | SNR salida (dB) | Mejora (dB) | Energía útil (%) | Criterio |',
            '|---|---|---:|---:|---:|---:|---|']
    for f in filas:
        lineas.append(f"| {f['caso']} | {f['metodo']} | {f['mse']:.6g} | {f['snr_salida_db']:.3f} | {f['mejora_snr_db']:.3f} | {f['energia_util_conservada_pct']:.3f} | {f['criterio_calidad']} |")
        print(f"{f['caso']} / {f['metodo']}: MSE={f['mse']:.3e}; mejora={f['mejora_snr_db']:.3f} dB; {f['criterio_calidad']}")
    lineas.extend(['\n## Interpretación y límites\n',
        'En los casos separados, compare MSE y SNR para determinar qué salida se aproxima más a la referencia. En superposición, compare además distorsión y energía útil: reducir ruido puede eliminar componentes útiles.',
        'La energía de salida total no equivale a energía útil conservada. Las componentes de evaluación del método espectral usan las máscaras aprendidas desde la mezcla.',
        'FIR se compensa 40 muestras en este diseño. La salida espectral es una referencia offline alineada. Esta comparación de calidad no elimina ni mide las latencias físicas.',
        'Los tiempos se miden de nuevo en cada máquina y ejecución. La RAM estimada no es una medición del consumo de Python ni del firmware.',
        'Para el artículo se deben explicar resultados y fallos, no copiar solo esta tabla. La propuesta de placa y comunicación sigue pendiente.'])
    (resultados/'comparacion_resumen.md').write_text('\n'.join(lineas)+'\n',encoding='utf-8')
    return {'metricas':filas,'tiempos':tiempos,'metadatos':auditoria,'salidas':salidas}


if __name__=='__main__':
    plt.switch_backend('Agg')
    ejecutar_comparacion()
