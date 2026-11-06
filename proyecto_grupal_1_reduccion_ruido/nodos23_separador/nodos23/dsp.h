// DSP común al ESP32-S3 y a la validación en PC. Una instancia por núcleo.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include "coeficientes.h"

namespace dsp {
constexpr int FS = 16000, N = 1024, H = N/2, K = H+1;
constexpr int NT = sizeof(FIR_B)/sizeof(float), RET = (NT-1)/2;
constexpr float PI_F = 3.14159265358979323846f;
constexpr int16_t SIN_REF = INT16_MIN;

struct Salto {
  int16_t x[H], ref[H];
  float fir[H], firLimpia[H];
  float finUtil;
  bool discontinuo;
};

struct Fir {
  // Anillo duplicado para recorrer las 81 muestras sin módulo en la suma.
  float h[2*NT]{};
  int pos = 0;
  float paso(float x) {
    h[pos] = h[pos+NT] = x;
    const float* p = h + pos + NT;
    float y = FIR_B[RET] * p[-RET];
    for (int k=0; k<RET; ++k) y += FIR_B[k]*(p[-k] + p[k+1-NT]);
    if (++pos == NT) pos = 0;
    return y;
  }
};
struct Temporal {
  Fir mezcla, limpia;
  int buenas = 0;
  void muestra(Salto& s, int i, int16_t x, int16_t r) {
    s.x[i] = x;
    s.ref[i] = r;
    s.fir[i] = mezcla.paso(x);
    float yr = limpia.paso(r == SIN_REF ? 0 : r);
    buenas = r == SIN_REF ? 0 : std::min(NT, buenas+1);
    s.firLimpia[i] = buenas == NT ? yr : NAN;
  }
};

struct Espectral {
  float w[N], invPeso[H], coseno[H], seno[H];
  float re[N], im[N], potencia[K], ruido[K], mascara[K], banda[K];
  float cola[H]{}, colaRef[H]{};
  bool iniciaRuido = true, colaRefValida = false;
  float corteAnterior = -1;

  void iniciar() {
    for (int i=0; i<N; ++i) w[i] = .5f-.5f*cosf(2*PI_F*i/N);
    for (int i=0; i<H; ++i) {
      coseno[i] = cosf(2*PI_F*i/N);
      seno[i] = sinf(2*PI_F*i/N);
      invPeso[i] = 1/(w[i]*w[i] + w[i+H]*w[i+H]);
    }
    reiniciar();
  }
  void reiniciar() {
    memset(cola, 0, sizeof cola);
    memset(colaRef, 0, sizeof colaRef);
    iniciaRuido = true;
    colaRefValida = false;
  }
  void fft(bool inversa) {
    for (int i=1,j=0; i<N; ++i) {
      int bit = N/2;
      while (j & bit) { j ^= bit; bit >>= 1; }
      j ^= bit;
      if (i<j) { std::swap(re[i],re[j]); std::swap(im[i],im[j]); }
    }
    for (int largo=2; largo<=N; largo*=2) {
      for (int base=0; base<N; base+=largo)
        for (int k=0; k<largo/2; ++k) {
          int a=base+k, b=a+largo/2, t=k*(N/largo);
          float c=coseno[t], s=inversa ? seno[t] : -seno[t];
          float r=c*re[b]-s*im[b], v=s*re[b]+c*im[b];
          re[b]=re[a]-r; im[b]=im[a]-v;
          re[a]+=r; im[a]+=v;
        }
    }
    // La normalización de IFFT se hace al aplicar la ventana de síntesis.
  }
  void analizar(const int16_t* a, const int16_t* b) {
    for (int i=0; i<H; ++i) {
      re[i]=a[i]*w[i]; re[i+H]=b[i]*w[i+H];
      im[i]=im[i+H]=0;
    }
    fft(false);
  }
  void estimar(float corte) {
    if (!(corte>0 && corte<0.95f*FS/2)) corte=1500;
    if (corte!=corteAnterior) {
      float fin=std::min(corte+800.f, .5f*(corte+FS/2));
      for (int k=0; k<K; ++k) {
        float u=std::max(0.f,std::min(1.f,(float(k)*FS/N-corte)/(fin-corte)));
        banda[k]=.001f+.999f*.5f*(1+cosf(PI_F*u));
      }
      corteAnterior=corte;
    }
    float pico=0;
    for (int k=0; k<K; ++k) {
      potencia[k]=re[k]*re[k]+im[k]*im[k];
      pico=std::max(pico,potencia[k]);
    }
    float eps=std::max(1e-20f,pico*1e-12f);
    for (int k=0; k<K; ++k) {
      float v[31];
      for (int j=-15; j<=15; ++j) {
        int b=k+j;
        if (b<0) b=-1-b;
        if (b>=K) b=2*K-1-b;
        v[j+15]=potencia[b];
      }
      std::nth_element(v,v+15,v+31);
      ruido[k]=iniciaRuido ? v[15] : .8f*ruido[k]+.2f*v[15];
      mascara[k]=banda[k]*sqrtf(std::max(.0025f,1-1.5f*ruido[k]/(potencia[k]+eps)));
    }
    iniciaRuido=false;
  }
  void sintetizar(float* pendiente, float* salida) {
    for (int k=0; k<N; ++k) {
      float g=mascara[std::min(k,N-k)];
      re[k]*=g; im[k]*=g;
    }
    fft(true);
    for (int i=0; i<H; ++i) {
      salida[i]=(pendiente[i]+re[i]*w[i]/N)*invPeso[i];
      pendiente[i]=re[i+H]*w[i+H]/N;
    }
  }
  // Entrega el salto a; el salto b aporta las muestras futuras de la ventana.
  bool procesar(const Salto& a, const Salto& b, float* y, float* limpia) {
    analizar(a.x,b.x);
    estimar(b.finUtil);
    sintetizar(cola,y);
    bool completa=true;
    for (int i=0; i<H && completa; ++i)
      completa=a.ref[i]!=SIN_REF && b.ref[i]!=SIN_REF;
    bool valida=completa && colaRefValida;
    if (completa) {
      analizar(a.ref,b.ref);
      sintetizar(colaRef,limpia);  // misma máscara que se aprendió de la mezcla
    } else memset(colaRef,0,sizeof colaRef);
    colaRefValida=completa;
    return valida;
  }
};
} // namespace dsp
