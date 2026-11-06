// Receptor v3 del nodo 1. Busca de nuevo dentro de una trama fallida.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
namespace uartv3 {
constexpr int CAB=92, MAX_N=2048, CHUNK=512, MAX_WIRE=CAB+4*MAX_N+4;
inline uint16_t u16(const uint8_t* p) { return p[0] | uint16_t(p[1])<<8; }
inline uint32_t u32(const uint8_t* p) { return u16(p) | uint32_t(u16(p+2))<<16; }
inline float f32(const uint8_t* p) { float f; memcpy(&f,p,4); return f; }
struct Receptor {
  uint8_t buf[MAX_WIRE+CHUNK];
  uint32_t tabla[256], crcMal=0, cabMal=0;
  int usados=0;
  void iniciar() {
    for (unsigned i=0; i<256; ++i) {
      uint32_t c=i;
      for (int k=0; k<8; ++k) c=(c>>1)^((c&1)?0xedb88320u:0u);
      tabla[i]=c;
    }
  }
  template<class F> void agregar(const uint8_t* datos, int n, F consumir) {
    while (n>0) {
      int parte=std::min(n,CHUNK);
      memcpy(buf+usados,datos,parte); usados+=parte; datos+=parte; n-=parte;
      int i=0;
      while (i<usados) {
        const uint8_t* p=buf+i;
        if (*p!=0xa5) { ++i; continue; }
        int quedan=usados-i;
        if (quedan<2) break;
        if (p[1]!=0x5a) { ++i; continue; }
        if (quedan<12) break;
        int m=u16(p+8);
        if (p[2]!=3 || p[3]!=CAB || m<1 || m>MAX_N) { ++cabMal; ++i; continue; }
        int largo=CAB+2*m*((u16(p+10)&64)?2:1)+4;
        if (quedan<largo) break;
        uint32_t crc=~0u;
        for (int j=2; j<largo-4; ++j) crc=tabla[(crc^p[j])&255]^(crc>>8);
        if (~crc!=u32(p+largo-4)) { ++crcMal; ++i; continue; }
        consumir(p); i+=largo;
      }
      if (i) { usados-=i; memmove(buf,buf+i,usados); }
    }
  }
};
}
