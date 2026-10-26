"""Reducción espectral adaptativa y reconstrucción WOLA de referencia.

Run Python File en VS Code o python -m src.filtrado_espectral.
La estimación usa SOLO la mezcla. Se conoce previamente la banda útil,
no la frecuencia exacta de la interferencia ni las referencias de evaluación.
"""
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.ndimage import median_filter
from scipy.signal import get_window, check_NOLA

if __package__ in (None, ''):
    from generacion import RAIZ, generar_todos, pcm16, snr_db
    from analisis import guardar_csv, guardar_figura, espectro_bloque
else:
    from .generacion import RAIZ, generar_todos, pcm16, snr_db
    from .analisis import guardar_csv, guardar_figura, espectro_bloque


def validar_config(config):
    N, H, fs = config['n_bloque'], config['salto'], config['fs_hz']
    if not isinstance(N, int) or N < 8 or N & (N-1):
        raise ValueError('n_bloque debe ser una potencia de dos, al menos 8.')
    if not isinstance(H, int) or not 0 < H <= N//2:
        raise ValueError('Use salto positivo y al menos 50% de solapamiento.')
    if not 0 < config['fin_banda_util_hz'] < config['inicio_rechazo_hz'] < fs/2:
        raise ValueError('La banda útil y la transición deben quedar bajo Nyquist.')
    if not 0 <= config['suavizado_ruido'] < 1:
        raise ValueError('El suavizado debe estar entre 0 (incluido) y 1 (excluido).')
    if config['alpha'] < 0 or not np.isfinite(config['alpha']):
        raise ValueError('alpha debe ser finito y no negativo.')
    if not 0 <= config['ganancia_minima'] <= 1 or not 0 <= config['ganancia_fuera_banda'] <= 1:
        raise ValueError('Las ganancias deben estar entre 0 y 1.')
    K = config['mediana_bins']
    if not isinstance(K,int) or K < 3 or K % 2 == 0 or K > N//2+1:
        raise ValueError('mediana_bins debe ser impar, entre 3 y el número de bins.')
    w = get_window('hann', N, fftbins=True)
    if not check_NOLA(w,N,N-H):
        raise ValueError('La ventana y el salto no permiten reconstrucción NOLA.')


class EstimadorEspectral:
    """Estado de estimación entre marcos consecutivos; nunca usa señal limpia.

    Supuesto: las componentes útiles son líneas más estrechas que la vecindad
    de la mediana. Puede eliminar audio útil de banda ancha o tonos débiles.
    """
    def __init__(self, config):
        validar_config(config)
        self.config = dict(config)
        self.ruido_estimado = None
        f = np.fft.rfftfreq(config['n_bloque'],1/config['fs_hz'])
        u = np.clip((f-config['fin_banda_util_hz']) /
                    (config['inicio_rechazo_hz']-config['fin_banda_util_hz']),0,1)
        # Información previa de banda, no frecuencia interferente fijada.
        self.ganancia_banda = config['ganancia_fuera_banda'] + (1-config['ganancia_fuera_banda'])*.5*(1+np.cos(np.pi*u))

    def estimar_ganancia(self, X):
        P = np.abs(X)**2
        local = median_filter(P, size=self.config['mediana_bins'], mode='reflect')
        beta = self.config['suavizado_ruido']
        if self.ruido_estimado is None:
            self.ruido_estimado = local
        else:
            self.ruido_estimado = beta*self.ruido_estimado + (1-beta)*local
        # Piso relativo evita división por cero y no depende de amplitud absoluta.
        eps = max(float(np.max(P))*1e-12, np.finfo(float).tiny)
        G = np.sqrt(np.maximum(1-self.config['alpha']*self.ruido_estimado/(P+eps),
                               self.config['ganancia_minima']**2))
        return G*self.ganancia_banda


def preparar_registro(x, N, H):
    """Padding de bordes; no altera el fs ni interpola los bins de cada FFT."""
    x = np.asarray(x)
    if x.ndim != 1 or len(x) == 0 or np.iscomplexobj(x) or not np.all(np.isfinite(x)):
        raise ValueError('La entrada debe ser un vector real finito no vacío.')
    x = x.astype(np.float64)
    pad = N//2
    extra = (-(len(x)+2*pad-N)) % H
    extendida = np.pad(x,(pad,pad+extra))
    inicios = np.arange(0,len(extendida)-N+1,H)
    return extendida, inicios, pad


def memoria_base_bytes(N):
    """Buffers de trabajo float32/complex64 para bloques de N muestras (K=N/2+1 bins).
    """
    K = N//2+1
    return 4*(5*N+4*K)+16*K


def reducir_espectral(x, config, reduccion=True, ganancias=None):
    """Referencia offline por marcos, con estado adaptativo causal por marco.

    WOLA: Hann de análisis Y de síntesis; normalización por suma de w**2.
    Devuelve longitud original con tiempo de referencia alineado. El padding
    y el recorte NO significan latencia física nula: el hardware deberá esperar
    las muestras necesarias y mantener buffers de solapamiento.

    ganancias permite reutilizar la máscara aprendida de la mezcla para
    evaluar sus componentes. No vuelve a aprender desde las referencias.
    """
    validar_config(config)
    N,H=config['n_bloque'],config['salto']
    extendida,inicios,pad=preparar_registro(x,N,H)
    w=get_window('hann',N,fftbins=True)
    estimador=EstimadorEspectral(config)
    forma=(len(inicios),N//2+1)
    if ganancias is not None:
        ganancias=np.asarray(ganancias,dtype=float)
        if ganancias.shape != forma or not np.all(np.isfinite(ganancias)) or np.any((ganancias<0)|(ganancias>1)):
            raise ValueError('Máscaras incompatibles con la longitud o fuera de [0,1].')
    mascaras=np.empty(forma)
    y=np.zeros_like(extendida)
    pesos=np.zeros_like(extendida)
    energia_ruido=[]
    for m,inicio in enumerate(inicios):
        X=np.fft.rfft(extendida[inicio:inicio+N]*w)
        G=(ganancias[m] if ganancias is not None else
           estimador.estimar_ganancia(X) if reduccion else np.ones(N//2+1))
        mascaras[m]=G
        Y=X*G  # Ganancia REAL no negativa: conserva fase y simetría conjugada.
        Y[0]=Y[0].real
        Y[-1]=Y[-1].real  # N siempre par: DC y Nyquist deben ser reales.
        marco=np.fft.irfft(Y,n=N)
        y[inicio:inicio+N] += marco*w
        pesos[inicio:inicio+N] += w*w
        if estimador.ruido_estimado is not None:
            energia_ruido.append(float(np.mean(estimador.ruido_estimado)))
    recorte=slice(pad,pad+len(x))
    if np.min(pesos[recorte]) <= 1e-12:
        raise AssertionError('Hay muestras sin cobertura suficiente para reconstruir.')
    salida=y[recorte]/pesos[recorte]
    return {'salida':salida,'ganancias':mascaras,'inicios':inicios,'pad_izquierdo':pad,
            'pesos_min':float(np.min(pesos[recorte])),
            'ruido_estimado_medio':np.asarray(energia_ruido)}


def evaluar_componentes(datos, procesado, config):
    """Congela las máscaras aprendidas en la mezcla: evaluación, no oráculo."""
    s,r,x=datos['limpia'],datos['ruido'],datos['contaminada']
    G=procesado['ganancias']
    ys=reducir_espectral(s,config,ganancias=G)['salida']
    yr=reducir_espectral(r,config,ganancias=G)['salida']
    y=procesado['salida']
    if not np.allclose(y,ys+yr,atol=1e-12,rtol=1e-10):
        raise AssertionError('La descomposición con máscaras congeladas no es consistente.')
    # Excluye N muestras por borde; no compensa un retardo físico medido.
    N=config['n_bloque']
    if len(s) <= 2*N:
        raise ValueError('Registro corto para la evaluación interior.')
    v=slice(N,len(s)-N)
    snr_in=snr_db(s[v],x[v]);snr_out=snr_db(s[v],y[v])
    resumen={'snr_entrada_db':snr_in,'snr_salida_db':snr_out,'mejora_snr_db':snr_out-snr_in,
             'mse':float(np.mean((s[v]-y[v])**2)),
             'energia_util_conservada_pct':float(100*np.sum(ys[v]**2)/np.sum(s[v]**2)),
             'distorsion_componente_util_mse':float(np.mean((s[v]-ys[v])**2)),
             'atenuacion_ruido_total_db':float(10*np.log10(np.sum(r[v]**2)/max(np.sum(yr[v]**2),np.finfo(float).tiny))),
             'inicio_evaluacion':N,'fin_evaluacion_exclusivo':len(s)-N,
             'pico_salida':float(max(abs(y))),
             'muestras_fuera_rango_pcm':int(np.count_nonzero(abs(y)>1))}
    return resumen,ys,yr


def figura_caso(nombre,datos,y,config,ruta):
    fs,N=config['fs_hz'],config['n_bloque'];inicio=int(.1*fs);vista=int(.01*fs)
    fig,axs=plt.subplots(2,1,figsize=(12,7))
    for etiqueta,senal in [('Limpia',datos['limpia']),('Contaminada',datos['contaminada']),('Espectral',y)]:
        axs[0].plot(datos['tiempo'][inicio:inicio+vista]*1000,senal[inicio:inicio+vista],label=etiqueta,alpha=.8)
        e=espectro_bloque(senal[inicio:inicio+N],fs)
        axs[1].plot(e['frecuencia_hz'],e['magnitud_db'],label=etiqueta)
    axs[0].set(xlabel='Tiempo de referencia (ms)',ylabel='Amplitud',title=f'{nombre}: referencia offline alineada; alpha={config["alpha"]}')
    axs[1].set(xlabel='Frecuencia (Hz)',ylabel='Amplitud (dB re 1)',ylim=(-110,5))
    for ax in axs:
        ax.grid(True,alpha=.25);ax.legend()
    guardar_figura(fig,ruta)


def ejecutar_espectral(casos=None):
    config=json.loads((RAIZ/'metadatos/filtro_espectral.json').read_text(encoding='utf-8-sig'))
    validar_config(config)
    casos=generar_todos() if casos is None else casos
    resultados=RAIZ/'resultados';figuras=resultados/'figuras'
    figuras.mkdir(parents=True,exist_ok=True)
    filas,salidas=[],{}
    for nombre,datos in casos.items():
        if datos['metadatos']['fs_hz'] != config['fs_hz']:
            raise ValueError('Muestreo de señales y método espectral no coincide.')
        identidad=reducir_espectral(datos['contaminada'],config,reduccion=False)
        error=float(max(abs(identidad['salida']-datos['contaminada'])))
        if error>config['tolerancia_reconstruccion']:
            raise AssertionError('La cadena sin reducción no reconstruye correctamente.')
        procesado=reducir_espectral(datos['contaminada'],config)
        medida,ys,yr=evaluar_componentes(datos,procesado,config)
        filas.append({'caso':nombre,'alpha':config['alpha'],'error_reconstruccion_max':error,**medida})
        carpeta=resultados/'espectral'/nombre;carpeta.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(carpeta/'salidas.npz',salida=procesado['salida'],salida_limpia=ys,salida_ruido=yr,
                            ganancias=procesado['ganancias'],inicios=procesado['inicios'])
        wavfile.write(carpeta/'salida_espectral.wav',config['fs_hz'],pcm16(procesado['salida']))
        figura_caso(nombre,datos,procesado['salida'],config,figuras/f'{nombre}_espectral.png')
        # Diagnóstico adaptativo: medias en banda útil y fuera de banda por marco.
        f=np.fft.rfftfreq(config['n_bloque'],1/config['fs_hz'])
        G=procesado['ganancias'];tiempo=(procesado['inicios']+config['n_bloque']//2-procesado['pad_izquierdo'])/config['fs_hz']
        guardar_csv(carpeta/'adaptacion.csv',[{'marco':i,'centro_s':float(tiempo[i]),
            'ganancia_media_banda_util':float(np.mean(G[i,f<=config['fin_banda_util_hz']])),
            'ganancia_media_fuera_banda':float(np.mean(G[i,f>=config['inicio_rechazo_hz']])),
            'potencia_ruido_estimada_media':float(procesado['ruido_estimado_medio'][i])} for i in range(len(G))])
        salidas[nombre]=procesado['salida']
    guardar_csv(resultados/'espectral_metricas.csv',filas)
    # Intensidades prefijadas: demuestra compromiso en la condición de solapamiento.
    datos=casos['caso_3'];experimento=[]
    for alpha in config['alphas_experimento']:
        variante={**config,'alpha':alpha}
        p=reducir_espectral(datos['contaminada'],variante)
        m,_,_=evaluar_componentes(datos,p,variante)
        experimento.append({'alpha':alpha,**m})
    guardar_csv(resultados/'espectral_compromiso.csv',experimento)
    fig,axs=plt.subplots(1,2,figsize=(12,4))
    alphas=[m['alpha'] for m in experimento]
    axs[0].plot(alphas,[m['atenuacion_ruido_total_db'] for m in experimento],'o-')
    axs[0].set(xlabel='Fuerza de reducción alpha',ylabel='Atenuación del ruido (dB)',title='Caso 3: reducción del ruido')
    axs[1].plot(alphas,[m['distorsion_componente_util_mse'] for m in experimento],'o-',color='tab:red')
    axs[1].set(xlabel='Fuerza de reducción alpha',ylabel='MSE del componente útil',title='Caso 3: distorsión de señal útil')
    for ax in axs:ax.grid(True,alpha=.25)
    guardar_figura(fig,figuras/'espectral_compromiso.png')
    N,H=config['n_bloque'],config['salto']
    resumen={**config,'ventana_analisis':'Hann periódica','ventana_sintesis':'Hann periódica',
             'normalizacion':'suma de cuadrados de ventanas','delta_f_hz':config['fs_hz']/N,
             'duracion_marco_ms':1000*N/config['fs_hz'],'intervalo_marcos_ms':1000*H/config['fs_hz'],
             'nota_latencia':'Salida offline alineada; la latencia física debe medirse en hardware.',
             'memoria_base_float32_complex64_bytes':memoria_base_bytes(N),
             'nota_memoria':'Estimación de buffers de trabajo; no incluye biblioteca FFT, pila, comunicación ni máscaras históricas offline.',
             'nota_metodo':'Mediana local y suavizado: heurística adaptativa, no estimador óptimo ni separación garantizada.',
             'informacion_previa':'Banda útil nominal; no se usan referencia limpia ni ruido aislado al estimar ganancias.'}
    (resultados/'espectral_diseno.json').write_text(json.dumps(resumen,indent=2,ensure_ascii=False),encoding='utf-8')
    for fila in filas:
        print(f"{fila['caso']}: error identidad={fila['error_reconstruccion_max']:.3e}; mejora SNR={fila['mejora_snr_db']:.3f} dB; energía útil={fila['energia_util_conservada_pct']:.2f}%")
    print('Experimento de compromiso:')
    for m in experimento:
        print(f"alpha={m['alpha']:g}: ruido atenuado {m['atenuacion_ruido_total_db']:.2f} dB; energía útil {m['energia_util_conservada_pct']:.2f}%; distorsión útil MSE={m['distorsion_componente_util_mse']:.6g}")
    return {'diseno':resumen,'metricas':filas,'salidas':salidas,'compromiso':experimento}


if __name__=='__main__':
    plt.switch_backend('Agg')
    ejecutar_espectral()
