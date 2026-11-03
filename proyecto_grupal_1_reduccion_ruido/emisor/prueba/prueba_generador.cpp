// Ejecuta generador.h en la computadora y guarda la salida (antes del DAC) en float32.
// Uso: prueba_generador salida.f32 muestras clave=valor ...
//   prueba=<1..5>  comp=mezcla|limpia|ruido  snr=<dB>  vol=<0..1>  semilla=n
//   util=tonos|audio|chirp:f0:f1:ms:periodo_s  tonos=f:a,f:a
//   ruido=ninguno|tono:f|blanco|banda:f1:f2|impulsivo:tasa
// Las claves se aplican en orden: prueba= primero y luego lo que se quiera cambiar.
// Lo usa verificar_generador.py; no forma parte del firmware.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../generador.h"

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "uso: %s salida.f32 muestras clave=valor ...\n", argv[0]);
    return 2;
  }
  Config c;
  c.activo = true;
  for (int i = 3; i < argc; ++i) {
    char* v = std::strchr(argv[i], '=');
    if (!v) return 2;
    *v++ = 0;
    const char* k = argv[i];
    if (!std::strcmp(k, "prueba")) { if (!cargarPrueba(std::atoi(v), c)) return 2; }
    else if (!std::strcmp(k, "comp"))
      c.componente = !std::strcmp(v, "limpia") ? Componente::Limpia : !std::strcmp(v, "ruido") ? Componente::Ruido : Componente::Mezcla;
    else if (!std::strcmp(k, "snr")) c.snr_db = std::strtof(v, nullptr);
    else if (!std::strcmp(k, "vol")) c.volumen = std::strtof(v, nullptr);
    else if (!std::strcmp(k, "semilla")) c.semilla = std::strtoul(v, nullptr, 10);
    else if (!std::strcmp(k, "util")) {
      char* p = std::strtok(v, ":");
      if (!std::strcmp(p, "audio")) c.util = TipoUtil::Audio;
      else if (!std::strcmp(p, "chirp")) {
        c.util = TipoUtil::Chirp;
        c.chirp_f[0] = std::strtof(std::strtok(nullptr, ":"), nullptr);
        c.chirp_f[1] = std::strtof(std::strtok(nullptr, ":"), nullptr);
        c.rafaga_ms = std::strtof(std::strtok(nullptr, ":"), nullptr);
        c.periodo_rafaga_s = std::strtof(std::strtok(nullptr, ":"), nullptr);
      } else c.util = TipoUtil::Tonos;
    } else if (!std::strcmp(k, "tonos")) {
      c.ntonos = 0;
      c.util = TipoUtil::Tonos;
      for (char* t = std::strtok(v, ","); t && c.ntonos < MAX_TONOS; t = std::strtok(nullptr, ",")) {
        char* fin;
        c.frec[c.ntonos] = std::strtof(t, &fin);
        c.amp[c.ntonos] = *fin == ':' ? std::strtof(fin + 1, nullptr) : 1.0f;
        ++c.ntonos;
      }
    } else if (!std::strcmp(k, "ruido")) {
      char* p = std::strtok(v, ":");
      if (!std::strcmp(p, "ninguno")) c.ruido = TipoRuido::Ninguno;
      else if (!std::strcmp(p, "blanco")) c.ruido = TipoRuido::Blanco;
      else if (!std::strcmp(p, "tono")) { c.ruido = TipoRuido::Tono; c.frec_ruido = std::strtof(std::strtok(nullptr, ":"), nullptr); }
      else if (!std::strcmp(p, "banda")) {
        c.ruido = TipoRuido::Banda;
        c.banda[0] = std::strtof(std::strtok(nullptr, ":"), nullptr);
        c.banda[1] = std::strtof(std::strtok(nullptr, ":"), nullptr);
      } else if (!std::strcmp(p, "impulsivo")) { c.ruido = TipoRuido::Impulsivo; c.tasa = std::strtof(std::strtok(nullptr, ":"), nullptr); }
    } else return 2;
  }
  Fuente f;
  calibrar(c, f);
  const long n = std::atol(argv[2]);
  std::FILE* salida = std::fopen(argv[1], "wb");
  if (!salida) return 1;
  for (long i = 0; i < n; ++i) {
    const float x = f.ganancia * f.valor();
    std::fwrite(&x, sizeof x, 1, salida);
  }
  std::fclose(salida);
  std::printf("ganancia=%.9g periodo=%u\n", f.ganancia, f.periodo);
  return 0;
}
