#pragma once
#include "dsp.h"

// Densidad espectral unilateral de Welch. Una fila por señal y un mismo
// conjunto de ventanas para las cuatro, cuando hay referencia suficiente.
namespace evidencia {
struct Espectros {
  float dbHz[4][dsp::K]{};
  unsigned marcos=0;
  bool conReferencia=false;

  template<class Muestra>
  static bool referenciaCompleta(const Muestra* clip,int inicio) {
    for (int i=0;i<dsp::N;++i)
      if (clip[inicio+i].ref==dsp::SIN_REF) return false;
    return true;
  }
  template<class Muestra, class Ceder>
  void calcular(const Muestra* clip,int cantidad,dsp::Espectral& fft,Ceder ceder) {
    memset(dbHz,0,sizeof dbHz);
    marcos=0; conReferencia=false;
    for (int inicio=0;inicio+dsp::N<=cantidad;inicio+=dsp::H)
      if (referenciaCompleta(clip,inicio)) { conReferencia=true; break; }
    float energiaVentana=0;
    for (float w:fft.w) energiaVentana+=w*w;
    for (int inicio=0;inicio+dsp::N<=cantidad;inicio+=dsp::H) {
      if (conReferencia && !referenciaCompleta(clip,inicio)) continue;
      for (int canal=conReferencia?0:1;canal<4;++canal) {
        for (int i=0;i<dsp::N;++i) {
          const Muestra& s=clip[inicio+i];
          const int16_t valores[]={s.ref,s.x,s.a,s.b};
          fft.re[i]=valores[canal]*fft.w[i];
          fft.im[i]=0;
        }
        fft.fft(false);
        for (int k=0;k<dsp::K;++k) {
          const float potencia=fft.re[k]*fft.re[k]+fft.im[k]*fft.im[k];
          const float factor=(k==0 || k==dsp::H) ? 1.f:2.f;
          dbHz[canal][k]+=factor*potencia/(dsp::FS*energiaVentana);
        }
        ceder();
      }
      ++marcos;
    }
    for (int canal=0;canal<4;++canal)
      for (int k=0;k<dsp::K;++k) {
        float& v=dbHz[canal][k];
        v=(marcos && (canal!=0 || conReferencia))
          ? 10*log10f(std::max(v/marcos,1e-20f)) : NAN;
      }
  }
};
}
