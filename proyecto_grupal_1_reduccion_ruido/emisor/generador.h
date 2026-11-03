/* Generador de señales del emisor, sin dependencias de Arduino.
 * Todo se calcula en vivo; solo la canción de P3 viene guardada (audio.h).
 * Lo usan emisor.ino y la prueba en computadora (prueba/prueba_generador.cpp).
 */
#pragma once
#include <math.h>
#include <stdint.h>
#include "audio.h"

constexpr float PICO = 0.8f;                 // Igual que pico_maximo de configuraciones.json.
constexpr float SNR_DEFECTO_DB = 2.0f;       // SNR de entrada de las pruebas (docs/señales.md)
constexpr uint32_t MAX_TONOS = 4;
constexpr float DOS_PI = 6.28318530718f;
constexpr int ORDEN_BANDA = 6;               // Igual que butter(6, ...) de src/generacion.py
constexpr float SIGMAS_GAUSS = 4.5f;         // margen de pico para ruido gaussiano
constexpr float TUKEY_ALFA = 0.25f;          // envolvente del chirp, igual que tukey(m, 0.25)

enum class Componente { Mezcla, Limpia, Ruido };
enum class TipoUtil { Tonos, Audio, Chirp };
enum class TipoRuido { Ninguno, Tono, Blanco, Banda, Impulsivo };

struct Config {
  bool activo = false;                       // false: silencio
  Componente componente = Componente::Mezcla;
  float snr_db = SNR_DEFECTO_DB;
  float volumen = 1.0f;
  TipoUtil util = TipoUtil::Tonos;
  uint32_t ntonos = 3;
  float frec[MAX_TONOS] = {440, 880, 1320, 0};
  float amp[MAX_TONOS] = {1.0f, 0.55f, 0.3f, 0};
  float chirp_f[2] = {600, 1400};            // ráfaga de barrido lineal, de amplitud 1
  float rafaga_ms = 50;
  float periodo_rafaga_s = 1;
  TipoRuido ruido = TipoRuido::Tono;
  float frec_ruido = 2508;
  float banda[2] = {2500, 3800};
  float tasa = 4;                            // impulsos por segundo
  uint32_t semilla = 1;
};

// Pruebas P1–P5 de la Tabla 1 de la especificación, con las señales de docs/señales.md.
// Conserva el volumen y la componente elegidos; el resto vuelve a su valor por defecto.
inline bool cargarPrueba(int p, Config& c) {
  Config n;
  n.activo = true;
  n.volumen = c.volumen;
  n.componente = c.componente;
  n.semilla = p;
  switch (p) {
    case 1: n.ntonos = 1; n.frec[0] = 440; n.amp[0] = 1; n.ruido = TipoRuido::Tono; n.frec_ruido = 2508; break;
    case 2: n.ruido = TipoRuido::Banda; n.banda[0] = 2500; n.banda[1] = 3800; break;
    case 3: n.util = TipoUtil::Audio; n.ruido = TipoRuido::Banda; n.banda[0] = 2000; n.banda[1] = 7500; break;
    case 4: n.util = TipoUtil::Chirp; n.ruido = TipoRuido::Impulsivo; n.tasa = 4; break;
    case 5: n.ruido = TipoRuido::Banda; n.banda[0] = 1000; n.banda[1] = 1800; break;
    default: return false;
  }
  c = n;
  return true;
}

// Sección de segundo orden en forma directa transpuesta II.
struct Biquad {
  float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
  float paso(float x) {
    const float y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};

// Pasa banda Butterworth de orden ORDEN_BANDA, igual que scipy.signal.butter: prototipo
// pasa bajos, transformación a pasa banda con bordes pre-deformados y bilineal.
// Llena ORDEN_BANDA secciones, cada una con un par de polos conjugados y ceros en z = ±1.
inline void disenarPasaBanda(float f1, float f2, Biquad* s) {
  const double pi = 3.14159265358979, fs2 = 2.0 * FS_HZ;
  const double w1 = fs2 * tan(pi * f1 / FS_HZ), w2 = fs2 * tan(pi * f2 / FS_HZ);
  const double ancho = w2 - w1, w0 = sqrt(w1 * w2);
  const double c0 = cos(2 * atan(w0 / fs2));   // cos de la frecuencia central digital
  int k = 0;
  for (int i = 0; i < ORDEN_BANDA; ++i) {
    // Polo del prototipo: p = e^{jθ}, θ en el semiplano izquierdo.
    const double th = pi * (2 * i + ORDEN_BANDA + 1) / (2 * ORDEN_BANDA);
    const double pr = cos(th) * ancho / 2, pim = sin(th) * ancho / 2;
    // s = p·B/2 ± sqrt((p·B/2)² − w0²), en complejos (re, im).
    const double dr = pr * pr - pim * pim - w0 * w0, di = 2 * pr * pim;
    const double m = sqrt(sqrt(dr * dr + di * di)), a = atan2(di, dr) / 2;
    for (int signo = -1; signo <= 1; signo += 2) {
      const double sr = pr + signo * m * cos(a), si = pim + signo * m * sin(a);
      if (si <= 0) continue;                   // de cada par conjugado se usa el polo de arriba
      // Bilineal: z = (fs2 + s) / (fs2 − s).
      const double nr = fs2 + sr, den = (fs2 - sr) * (fs2 - sr) + si * si;
      const double zr = (nr * (fs2 - sr) - si * si) / den, zi = (si * (fs2 - sr) + nr * si) / den;
      Biquad& b = s[k++];
      b.a1 = -2 * zr;
      b.a2 = zr * zr + zi * zi;
      // Numerador 1 − z⁻²; se normaliza a ganancia 1 en la frecuencia central.
      const double s0 = sqrt(1 - c0 * c0), c2 = 2 * c0 * c0 - 1, s2 = 2 * s0 * c0;
      const double numR = 1 - c2, numI = s2;
      const double denR = 1 + b.a1 * c0 + b.a2 * c2, denI = -(b.a1 * s0 + b.a2 * s2);
      const double g = sqrt((denR * denR + denI * denI) / (numR * numR + numI * numI));
      b.b0 = g;
      b.b1 = 0;
      b.b2 = -g;
      b.z1 = b.z2 = 0;
    }
  }
}

// Genera la señal configurada; se copia para calibrar sin alterar el estado de reproducción.
struct Fuente {
  Config cfg;
  float ganancia = 0;                        // lleva el pico de la mezcla a PICO * volumen
  uint32_t periodo = 0;                      // muestras por ciclo de la señal útil (marca el pulso de sincronización)
  uint32_t indice = 0;                       // posición dentro del ciclo
  uint32_t muestrasRafaga = 0;
  float chirpA = 0, chirpB = 0;              // fase del chirp: chirpA·n + chirpB·n²
  uint32_t bordeTukey = 0;
  float alturaImpulso = 0;
  float fase[MAX_TONOS] = {}, paso[MAX_TONOS] = {}, faseRuido = 0, pasoRuido = 0;
  float escalaRuido = 0, normaBanda = 1;
  // El pasa banda se aplica dos veces: misma magnitud |H|² que sosfiltfilt en generacion.py.
  Biquad filtro[2 * ORDEN_BANDA];
  uint32_t rng = 1;
  bool hayGauss = false;
  float gauss = 0;

  void iniciar(const Config& c) {
    cfg = c;
    indice = 0;
    escalaRuido = 0;
    normaBanda = 1;
    periodo = c.util == TipoUtil::Audio ? AUDIO_N
            : c.util == TipoUtil::Chirp ? (uint32_t)lrintf(c.periodo_rafaga_s * FS_HZ) : FS_HZ;
    // Chirp como scipy.signal.chirp(t, f0, T, f1) con T = (m − 1)/fs: fase 2π(f0·t + β·t²/2).
    muestrasRafaga = (uint32_t)lrintf(c.rafaga_ms * FS_HZ / 1000);
    const float m1 = muestrasRafaga > 1 ? muestrasRafaga - 1.0f : 1.0f;
    chirpA = DOS_PI * c.chirp_f[0] / FS_HZ;
    chirpB = DOS_PI * (c.chirp_f[1] - c.chirp_f[0]) / (2.0f * FS_HZ * m1);
    bordeTukey = (uint32_t)floorf(TUKEY_ALFA * m1 / 2);
    alturaImpulso = sqrtf(FS_HZ / c.tasa);     // impulso de una muestra con potencia media 1
    for (uint32_t i = 0; i < MAX_TONOS; ++i) {
      fase[i] = 0;
      paso[i] = DOS_PI * c.frec[i] / FS_HZ;
    }
    faseRuido = 0;
    pasoRuido = DOS_PI * c.frec_ruido / FS_HZ;
    disenarPasaBanda(c.banda[0], c.banda[1], filtro);
    disenarPasaBanda(c.banda[0], c.banda[1], filtro + ORDEN_BANDA);
    rng = c.semilla ? c.semilla : 1;           // xorshift no admite estado cero
    hayGauss = false;
  }

  float uniforme() {                           // (0, 1], xorshift32
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return ((rng >> 8) + 1) * (1.0f / 16777216.0f);
  }

  float normal() {                             // Box-Muller: dos valores por cada par de uniformes
    if (hayGauss) { hayGauss = false; return gauss; }
    const float r = sqrtf(-2 * logf(uniforme())), t = DOS_PI * uniforme();
    gauss = r * sinf(t);
    hayGauss = true;
    return r * cosf(t);
  }

  float utilActual() {
    float v = 0;
    switch (cfg.util) {
      case TipoUtil::Tonos:
        for (uint32_t i = 0; i < cfg.ntonos; ++i) {
          v += cfg.amp[i] * sinf(fase[i]);
          fase[i] += paso[i];
          if (fase[i] >= DOS_PI) fase[i] -= DOS_PI;
        }
        break;
      case TipoUtil::Audio: v = AUDIO[indice] * (1.0f / 127); break;
      case TipoUtil::Chirp:
        if (indice < muestrasRafaga) {
          const float n = (float)indice, m1 = muestrasRafaga - 1.0f;
          // Envolvente Tukey, simétrica: bordes de coseno y centro plano.
          const float d = fminf(n, m1 - n);
          const float env = d > bordeTukey ? 1.0f : 0.5f * (1 + cosf(3.14159265f * (-1 + 2 * d / (TUKEY_ALFA * m1))));
          v = env * cosf(chirpA * n + chirpB * n * n);
        }
        break;
    }
    if (++indice >= periodo) indice = 0;
    return v;
  }

  float ruidoUnitario() {                      // potencia media 1, salvo la banda (se normaliza aparte)
    switch (cfg.ruido) {
      case TipoRuido::Tono: {
        const float v = 1.41421356f * sinf(faseRuido);
        faseRuido += pasoRuido;
        if (faseRuido >= DOS_PI) faseRuido -= DOS_PI;
        return v;
      }
      case TipoRuido::Blanco: return normal();
      case TipoRuido::Banda: {
        float v = normal();
        for (auto& f : filtro) v = f.paso(v);
        return v * normaBanda;
      }
      case TipoRuido::Impulsivo:
        if (uniforme() * FS_HZ > cfg.tasa) return 0;
        return (uniforme() < 0.5f ? -1 : 1) * alturaImpulso;
      default: return 0;
    }
  }

  float valor() {                              // muestra antes de la ganancia de salida
    if (!cfg.activo) return 0;
    // Se calculan ambas siempre para que limpia, ruido y mezcla queden alineadas en el tiempo.
    const float util = utilActual(), ruido = escalaRuido * ruidoUnitario();
    if (cfg.componente == Componente::Limpia) return util;
    if (cfg.componente == Componente::Ruido) return ruido;
    return util + ruido;
  }
};

// Potencia media de la señal útil en un ciclo, para fijar la SNR.
inline float potenciaUtil(const Fuente& f) {
  const Config& c = f.cfg;
  if (c.util == TipoUtil::Audio) return AUDIO_POTENCIA;
  if (c.util == TipoUtil::Chirp) {             // medida sobre un ciclo
    Fuente p = f;
    p.indice = 0;
    double suma = 0;
    for (uint32_t i = 0; i < p.periodo; ++i) { const float u = p.utilActual(); suma += u * u; }
    return suma / p.periodo;
  }
  float ps = 0;
  for (uint32_t i = 0; i < c.ntonos; ++i) ps += c.amp[i] * c.amp[i] / 2;
  return ps;
}

// Escala del ruido y ganancia de salida; trabaja sobre copias para no avanzar el estado de f.
inline void calibrar(const Config& c, Fuente& f) {
  f.iniciar(c);
  f.ganancia = 0;
  if (!c.activo) return;
  if (c.ruido == TipoRuido::Banda) {          // potencia del filtro medida, no supuesta
    Fuente p = f;
    double suma = 0;
    for (uint32_t i = 0; i < 2 * FS_HZ; ++i) { const float v = p.ruidoUnitario(); suma += v * v; }
    f.normaBanda = 1 / sqrtf(suma / (2 * FS_HZ));
  }
  f.escalaRuido = c.ruido == TipoRuido::Ninguno ? 0 : sqrtf(potenciaUtil(f) / powf(10, c.snr_db / 10));
  // El pico se mide siempre sobre la mezcla: así limpia y ruido salen con la misma ganancia
  // que tienen dentro de la mezcla y sirven como referencia capturada por el mismo canal.
  Fuente p = f;
  p.cfg.componente = Componente::Mezcla;
  float pico = 0, picoUtil = 0;
  for (uint32_t i = 0; i < f.periodo; ++i) {
    const float u = p.utilActual();
    picoUtil = fmaxf(picoUtil, fabsf(u));
    pico = fmaxf(pico, fabsf(u + p.escalaRuido * p.ruidoUnitario()));
  }
  if (c.ruido == TipoRuido::Impulsivo)         // en un ciclo corto puede no caer ningún impulso
    pico = fmaxf(pico, f.escalaRuido * f.alturaImpulso + picoUtil);
  if (c.ruido == TipoRuido::Blanco || c.ruido == TipoRuido::Banda)
    // Gaussiano: un ciclo no muestra sus picos más altos. |x| > 4.5σ ocurre en < 1e-5 de las muestras.
    pico = fmaxf(pico, picoUtil + SIGMAS_GAUSS * f.escalaRuido);
  f.ganancia = pico > 0 ? PICO * c.volumen / pico : 0;
}
