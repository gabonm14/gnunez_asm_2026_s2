"""Métricas auditables; referencias reservadas exclusivamente a evaluación."""
import numpy as np


def intervalo_comun(longitud, n_bloque, orden_fir, retardo_fir):
    """Referencia [inicio,fin); el FIR se lee en [inicio+D,fin+D)."""
    inicio=max(n_bloque,orden_fir)
    fin=longitud-n_bloque-retardo_fir
    if fin<=inicio:
        raise ValueError('Registro insuficiente para el intervalo común.')
    return inicio,fin


def frecuencia_dominante(ruido,fs):
    """Bin de máxima energía del ruido aislado, solo para evaluación."""
    r=np.asarray(ruido,dtype=float)
    w=np.hanning(len(r))
    f=np.fft.rfftfreq(len(r),1/fs)
    return float(f[np.argmax(abs(np.fft.rfft(r*w))**2)])


def amplitud_componente(x,fs,frecuencia):
    """Proyección por mínimos cuadrados sobre seno/coseno de la frecuencia."""
    x=np.asarray(x,dtype=float)
    t=np.arange(len(x))/fs
    if frecuencia==0:
        return float(abs(np.mean(x)))
    if np.isclose(frecuencia,fs/2,atol=1e-9,rtol=0):
        return float(abs(np.mean(x*(-1.)**np.arange(len(x)))))
    bases=np.column_stack([np.cos(2*np.pi*frecuencia*t),np.sin(2*np.pi*frecuencia*t)])
    coef=np.linalg.lstsq(bases,x,rcond=None)[0]
    return float(np.linalg.norm(coef))


def medir_calidad(limpia,entrada,salida,limpia_filtrada,ruido_filtrado,fs,f_dominante):
    """Arrays alineados y de igual longitud. No normaliza amplitud ni fase."""
    arrays=[np.asarray(x,dtype=float) for x in (limpia,entrada,salida,limpia_filtrada,ruido_filtrado)]
    s,x,y,ys,yr=arrays
    if any(a.ndim!=1 or len(a)!=len(s) or not np.all(np.isfinite(a)) for a in arrays) or not len(s):
        raise ValueError('Se requieren vectores finitos de igual longitud.')
    Es=float(np.sum(s*s))
    if Es==0:
        raise ValueError('Referencia con energía nula.')
    Ein=float(np.sum((s-x)**2));Eout=float(np.sum((s-y)**2))
    Er=float(np.sum((x-s)**2));Erout=float(np.sum(yr*yr))
    def cociente_db(numerador,denominador):
        return float(10*np.log10(numerador/denominador)) if denominador>0 else float('inf')
    snr_in=cociente_db(Es,Ein);snr_out=cociente_db(Es,Eout)
    ain=amplitud_componente(x-s,fs,f_dominante)
    aout=amplitud_componente(yr,fs,f_dominante)
    atenuacion=float(20*np.log10(ain/aout)) if min(ain,aout)>0 else float('inf') if ain>0 else float('nan')
    return {'mse':Eout/len(s),'snr_entrada_db':snr_in,'snr_salida_db':snr_out,
            'mejora_snr_db':snr_out-snr_in,'energia_util_conservada_pct':100*float(np.sum(ys*ys))/Es,
            'distorsion_util_mse':float(np.mean((s-ys)**2)),
            'atenuacion_ruido_total_db':cociente_db(Er,Erout),
            'frecuencia_dominante_ruido_hz':f_dominante,'atenuacion_componente_dominante_db':atenuacion}
