/* Nodo 1: adquisición, análisis y comunicación. ESP32 DevKit de 38 pines (ESP32-WROOM-32),
 * Arduino-ESP32 3.3.x (compilado con 3.3.11, placa "ESP32 Dev Module"; ya incluye esp-dsp).
 *
 * Cadena: emisor -> DAC -> PAM8403 -> parlante -> aire -> micrófono MAX4466 -> RC -> ADC.
 *
 * 1) Captura: ADC1 (GPIO34) a 16 kHz exactos por temporizador, doble búfer de 1024 muestras,
 *    secuencia, marca de tiempo, nivel mín./máx. y detección de recorte, atraso,
 *    desbordamiento y fs fuera de tolerancia. La DC del micrófono (~1.65 V) se sigue con un
 *    pasa altos suave muestra a muestra, sin saltos entre bloques.
 * 2) Procesamiento: DC por marco, Hann periódica, FFT con esp-dsp y PSD promediada.
 * 3) Diagnóstico: traducción de diagnosticar() de src/diagnostico.py, repetido cada periodo.
 * 4) Comunicación: trama por UART2 (GPIO17) con delimitador, secuencia, estado, parámetros
 *    del diagnóstico, muestras y CRC-32 hacia los nodos 2 y 3.
 * 5) Consola serie (USB): parámetros sin recompilar, pruebas, tiempos y memoria.
 * 6) Sincronización con el emisor (GPIO27 -> GPIO35) y referencia limpia para el MSE del nodo 3:
 *    se guarda un ciclo de la señal limpia tal como llega al micrófono y viaja en cada trama
 *    (docs/nodo1_verificacion.md, "Referencia limpia para el MSE").
 *
 * Fuera de Arduino (sin ARDUINO definido) este mismo archivo se compila en la PC con
 * nodo1/host/Makefile: la FFT es una radix-2 de referencia y la consola usa stdin/stdout.
 * Así los scripts de nodo1/validacion/ prueban el mismo código con y sin placa.
 */
#include <float.h>
#include <math.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <algorithm>

#ifdef ARDUINO
#include <Arduino.h>
#include <atomic>
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_dsp.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "hal/gpio_ll.h"
#else
#include <unistd.h>
#include <chrono>
#endif

// ============================================================================
// Tipos y constantes (antes de cualquier función: Arduino genera prototipos)
// ============================================================================

constexpr int N_MIN = 64;
constexpr int N_MAX = 2048;   // la tabla de esp-dsp se inicializa una vez para este tamaño
constexpr int MAX_RED = 2;
constexpr int MAX_ARMONICO = 32;
constexpr int MAX_REGIONES = 48;
constexpr int MAX_PICOS = N_MAX / 6 + 2;  // un máximo local por cada 3 bins como mucho

// Mismos nombres y valores por defecto que metadatos/diagnostico.json y filtro_espectral.json.
struct ConfigNodo1 {
  float fs_hz = 16000;
  int n_bloque = 1024;
  float periodo_diag_ms = 1000;   // pipeline.json: segundos_diagnostico
  float umbral_ocupacion_db = 40;
  int hueco_fusion_bins = 3;
  float ancho_linea_hz = 100;
  float ancho_dc_hz = 100;
  float hueco_util_hz = 1000;
  float margen_banda_util_hz = 100;
  float umbral_curtosis = 20;
  float k_atipicas_mad = 8;
  float frecuencias_red_hz[MAX_RED] = {50, 60};
  int armonicos_red_min = 3;
  int max_armonico_red = 10;
  float tolerancia_red_hz = 4;
};

enum Etapa { ETAPA_DC_VENTANA, ETAPA_FFT, ETAPA_PSD, ETAPA_IMPULSOS, ETAPA_DIAGNOSTICO, N_ETAPAS };
const char* const NOMBRES_ETAPA[N_ETAPAS] = {"dc_ventana", "fft", "psd", "impulsos", "diagnostico"};

struct Cronometro {
  uint32_t n;
  int64_t total_us;
  int32_t max_us, ultimo_us;
  void registrar(int32_t us) {
    ++n;
    total_us += us;
    ultimo_us = us;
    if (us > max_us) max_us = us;
  }
};

struct EstadoDsp {
  int N;
  float* ventana;    // N, Hann periódica
  float* marco;      // N, muestras del marco en curso; salto N/2 (50 % de solapamiento)
  float* fft;        // 2N, re/im intercalados, alineado a 16 B para esp-dsp
  float* psd;        // N/2+1, suma de |X[k]|^2 de los marcos del periodo
  float* db;         // N/2+1, usado por el diagnóstico
  uint8_t* mascara;  // N/2+1, usado por el diagnóstico
  float* dif;        // N, primera diferencia pendiente de la estadística de impulsos
  float* trabajo;    // N, copia para nth_element (medianas)
  size_t bytes;      // memoria dinámica propia
  int llenado;
  uint32_t marcos, muestras;
  // Impulsividad: momentos de la diferencia centrada en su mediana por trozo de N.
  int n_dif;
  bool hay_previa, atipica_previa;
  float previa, mediana_previa, mad_previa;
  double s2, s4;
  uint32_t n_d, eventos;
  Cronometro t[N_ETAPAS];
};

enum TipoRuido : uint8_t { TIPO_IMPULSIVO = 1, TIPO_RED = 2, TIPO_TONAL = 4, TIPO_BANDA = 8 };
const char* const NOMBRES_TIPO[] = {"impulsivo", "red_electrica", "tonal", "banda"};

struct Region {
  float f_lo, f_hi, f_pico, ancho, nivel_db, potencia;
  int k;        // bin del máximo
  bool linea;   // ancho <= ancho_linea_hz
  bool red;     // armónico de 50/60 Hz
};

struct Pico {
  int k;
  float f;
};

struct Diagnostico {
  uint32_t numero, muestras, marcos;
  uint32_t fin_muestra;                  // índice absoluto de la muestra que cerró el periodo
  const char* tipo;
  const char* motivo;
  uint8_t tipos;  // combinación de TipoRuido
  bool confiable, solapamiento, senal_banda_ancha, impulsivo;
  float frecuencia_red_hz;               // NAN si no hay familia de red
  float banda_ruido_hz[2];               // NAN si no hay banda
  float bloque_util_hz[2];               // NAN si no hay bloque
  float fin_banda_util_hz;               // NAN si la confianza es baja
  float snr_estimada_db, curtosis, impulsos_por_s;
  int n_lineas;
  float lineas_hz[MAX_REGIONES];         // frecuencias_interferentes_hz, ordenadas
  int n_regiones, n_interferencias;
  Region regiones[MAX_REGIONES], interferencias[MAX_REGIONES];
  bool truncado;                         // se llenó alguna lista fija
  float tiempo_ms;
};

// ---- Sincronización con el emisor y referencia limpia (docs/nodo1_verificacion.md) ----
// El emisor marca el inicio de cada ciclo de su señal con un pulso cuyo ancho dice qué emite:
// 1 ms mezcla, 2 ms limpia, 3 ms ruido; en silencio no hay pulsos.
constexpr int REF_MAX = 32000;             // 2 s: un ciclo de 1 s entero o los primeros 2 s de la canción
constexpr int REF_K_MAX = 8;               // 8 ciclos con |x| <= 4095 suman <= 32760: la suma cabe en int16
constexpr int16_t REF_SIN = INT16_MIN;     // "sin referencia" para esa muestra; |x| <= 4095 nunca llega
constexpr uint32_t REF_TOLERANCIA = 2;     // muestras de diferencia admitidas entre periodos

enum Componente : uint8_t { COMP_NINGUNA = 0, COMP_MEZCLA = 1, COMP_LIMPIA = 2, COMP_RUIDO = 3 };
const char* const NOMBRES_COMP[] = {"ninguna", "mezcla", "limpia", "ruido"};
enum EstadoRef : uint8_t { REF_VACIA = 0, REF_ESPERANDO = 1, REF_CAPTURANDO = 2, REF_LISTA = 3 };
const char* const NOMBRES_REF[] = {"vacia", "esperando", "capturando", "lista"};
enum EventoRef { EV_NADA, EV_LISTA, EV_CANCELADA };

struct Sincronia {        // una lectura del pin por muestra
  bool hay;               // hubo un flanco de subida y no se perdió la cuenta desde entonces
  bool nivel;             // nivel de la muestra anterior
  uint32_t pos;           // posición en el ciclo: muestras desde el último flanco de subida
  uint32_t alto;          // muestras en alto del pulso en curso
  uint32_t periodo;       // muestras entre los dos últimos flancos; 0 si aún no se midió
  uint32_t ancho;         // muestras en alto del último pulso completo
  uint32_t pulsos;
  uint8_t componente;     // según el ancho del último pulso
};

struct Referencia {       // un ciclo de la limpia, en las mismas unidades que las muestras de la trama
  int16_t* datos;         // REF_MAX
  uint8_t estado;
  uint32_t largo;         // muestras guardadas: min(periodo, REF_MAX)
  uint32_t periodo;       // periodo del emisor al capturarla; con otro periodo no se aplica
  int ciclos, hechos;
  const char* motivo;     // por qué se canceló la última captura
};

// Arma texto con printf sin pasarse de la capacidad del buffer.
struct Escritor {
  char* buf;
  int cap, n;
  __attribute__((format(printf, 2, 3))) void add(const char* fmt, ...) {
    if (n >= cap - 1) return;
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(buf + n, cap - n, fmt, ap);
    va_end(ap);
    if (n > cap - 1) n = cap - 1;
  }
  void num(float v) { isfinite(v) ? add("%.6g", v) : add("null"); }
  void par(float a, float b) {
    if (!isfinite(a)) return add("null");
    add("[");
    num(a);
    add(",");
    num(b);
    add("]");
  }
};

struct Nodo1 {
  ConfigNodo1 cfg;
  EstadoDsp dsp;
  Diagnostico diag;
  void (*escribir)(const char* texto);                           // destino de las respuestas
  int (*memoria_plataforma)(char* buf, int cap);                 // pares JSON extra para MEM
  bool (*comando_plataforma)(const char* cmd, const char* arg);  // comandos propios de la placa
  // Estado de la consola.
  char linea[96];
  int n_linea;
  uint32_t binario_pendiente;  // muestras float32 que faltan por recibir
  bool binario_periodico;
  bool binario_tramas;         // emitir una TRAMA por cada BLOQUE_ADC muestras recibidas
  int llenado_trama;
  uint32_t seq_trama;
  uint8_t parcial[4];
  int n_parcial;
  uint32_t muestras_totales;   // índice absoluto (la captura lo fija a seq * BLOQUE_ADC)
  const float* bloque_real;    // último bloque del ADC para fft_prueba adc (nullptr en la PC)
  bool enviar_espectro;        // "espectro on": línea PSD tras cada DIAG, para graficar en la PC
  Sincronia sync;
  Referencia ref;
};

// ---- Trama hacia los nodos 2 y 3 (formato en README y en validacion/trama.py) ----
constexpr int BLOQUE_ADC = 1024;           // doble búfer del ADC: 64 ms a 16 kHz
constexpr int TRAMA_CABECERA = 92;         // incluye el delimitador
constexpr int TRAMA_MAX = TRAMA_CABECERA + 4 * N_MAX + 4;  // muestras y, si la hay, referencia
constexpr uint8_t TRAMA_SYNC0 = 0xA5, TRAMA_SYNC1 = 0x5A, TRAMA_VERSION = 3;
constexpr int MAX_LINEAS_TRAMA = 4;

enum EstadoTrama : uint16_t {
  EST_RECORTE = 1,      // alguna muestra del bloque en 0 o 4095
  EST_ATRASO = 2,       // la tarea del ADC llegó tarde: muestras repetidas en el bloque
  EST_PERDIDA = 4,      // se perdieron bloques desde la trama anterior (desbordamiento)
  EST_DIAG_NUEVO = 8,   // los parámetros del diagnóstico cambiaron desde la trama anterior
  EST_FS_FUERA = 16,    // la fs medida se aleja más de 0.5 % de la nominal
  EST_PRUEBA = 32,      // las muestras no vienen del ADC (fuente sintética o patrón)
  EST_REF = 64,         // tras las muestras viaja la referencia limpia del mismo tramo
};

struct InfoBloque {     // lo que acompaña a cada bloque de muestras en la trama
  uint32_t seq;
  uint16_t estado, recortadas, atrasadas;
  uint32_t perdidos;    // bloques perdidos acumulados
  float fs_medida_hz;
  uint16_t dc;          // nivel de DC restado, en código del ADC
  uint32_t t_us;        // esp_timer al cerrar el bloque (módulo 2^32)
  bool hay_sync = false;      // se conoce la posición en el ciclo del emisor
  uint32_t pos_ciclo = 0;     // posición en el ciclo de la primera muestra del bloque
  int16_t inicio_ciclo = -1;  // índice dentro del bloque donde empieza un ciclo; -1 si ninguno
  uint8_t componente = COMP_NINGUNA, ref_estado = REF_VACIA;
};

struct Receptor {       // decodificador de tramas byte a byte (prueba y lazo UART2)
  uint8_t buf[TRAMA_MAX];
  int n, esperado;
  uint32_t ok, errores_crc, perdidas, descartados, ultima_seq;
  bool hay_seq;
};

struct Bloque {         // de la tarea del ADC a loop(), por la cola
  int idx;
  uint32_t seq, perdidos;
  uint16_t recortadas, atrasadas;
  int64_t t_us;
};

enum Fuente { FUENTE_ADC, FUENTE_SINT, FUENTE_PATRON, FUENTE_NADA };

// Parámetros ajustables sin recompilar. Las claves son las de metadatos/*.json.
struct Parametro {
  const char* clave;
  const char* alias;
  size_t desplazamiento;
  bool entero;
  float minimo, maximo;
};
#define P_(campo, alias, entero, mn, mx) {#campo, alias, offsetof(ConfigNodo1, campo), entero, mn, mx}
const Parametro PARAMETROS[] = {
#ifdef ARDUINO
    P_(fs_hz, "fs", false, 16000, 16000),  // fijada por el temporizador del ADC
#else
    P_(fs_hz, "fs", false, 1000, 100000),
#endif
    P_(n_bloque, "n", true, N_MIN, N_MAX),
    P_(periodo_diag_ms, "periodo", false, 0, 60000),  // 0: solo diagnóstico manual
    P_(umbral_ocupacion_db, "umbral", false, 3, 120),
    P_(hueco_fusion_bins, nullptr, true, 0, 64),
    P_(ancho_linea_hz, nullptr, false, 0, 10000),
    P_(ancho_dc_hz, nullptr, false, 0, 10000),
    P_(hueco_util_hz, nullptr, false, 0, 50000),
    P_(margen_banda_util_hz, nullptr, false, 0, 10000),
    P_(umbral_curtosis, "curtosis", false, 0, 1e6),
    P_(k_atipicas_mad, "kmad", false, 0.5, 1000),
    {"frecuencia_red_a_hz", "red_a", offsetof(ConfigNodo1, frecuencias_red_hz), false, 0, 1000},
    {"frecuencia_red_b_hz", "red_b", offsetof(ConfigNodo1, frecuencias_red_hz) + sizeof(float), false, 0, 1000},
    P_(armonicos_red_min, nullptr, true, 1, MAX_ARMONICO),
    P_(max_armonico_red, nullptr, true, 1, MAX_ARMONICO),
    P_(tolerancia_red_hz, nullptr, false, 0, 100),
};
constexpr int N_PARAMETROS = sizeof(PARAMETROS) / sizeof(PARAMETROS[0]);
constexpr int I_FS = 0, I_N = 1;  // posiciones con efectos al cambiar

// Estáticos: la pila de loop() es de 8 KB y estas listas ocupan ~6 KB.
static Pico picos[MAX_PICOS];
static Region red[MAX_ARMONICO], bloque[MAX_REGIONES];
static char salida[6144];  // una respuesta DIAG con 2x48 regiones cabe con margen
static Nodo1 nodo;
static uint8_t trama_tx[TRAMA_MAX];
static int16_t muestras_tx[BLOQUE_ADC];
static int16_t ref_tx[BLOQUE_ADC];        // referencia del bloque que viaja en la trama
static uint32_t tabla_crc[256];

void responder(Nodo1& n, const char* fmt, ...) __attribute__((format(printf, 2, 3)));

// ============================================================================
// Plataforma: reloj, memoria y FFT
// ============================================================================

#ifdef ARDUINO
int64_t micros64() { return esp_timer_get_time(); }

// RAM interna: la PSRAM, si existe, es lenta para la FFT.
void* reservar(size_t bytes) { return heap_caps_aligned_alloc(16, bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT); }
void liberar(void* p) { heap_caps_free(p); }

// Tabla de factores de giro para N_MAX; sirve para cualquier N <= N_MAX potencia de dos.
bool iniciar_fft() { return dsps_fft2r_init_fc32(NULL, N_MAX) == ESP_OK; }

// Radix-2 de esp-dsp (en el ESP32 la macro elige la versión optimizada ae32) y reordenamiento.
void fft_compleja(float* d, int N) {
  dsps_fft2r_fc32(d, N);
  dsps_bit_rev_fc32(d, N);
}
#else
int64_t micros64() {
  using namespace std::chrono;
  return duration_cast<microseconds>(steady_clock::now().time_since_epoch()).count();
}

void* reservar(size_t bytes) { return aligned_alloc(16, (bytes + 15) & ~size_t(15)); }
void liberar(void* p) { free(p); }
bool iniciar_fft() { return true; }

// Referencia de PC: radix-2 iterativa en float, misma convención que esp-dsp y NumPy.
void fft_compleja(float* d, int N) {
  for (int i = 1, j = 0; i < N; ++i) {
    int bit = N >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      std::swap(d[2 * i], d[2 * j]);
      std::swap(d[2 * i + 1], d[2 * j + 1]);
    }
  }
  for (int len = 2; len <= N; len <<= 1) {
    for (int k = 0; k < len / 2; ++k) {
      const float wr = (float)cos(-2 * M_PI * k / len), wi = (float)sin(-2 * M_PI * k / len);
      for (int i = k; i < N; i += len) {
        float* a = d + 2 * i;
        float* b = d + 2 * (i + len / 2);
        const float tr = b[0] * wr - b[1] * wi, ti = b[0] * wi + b[1] * wr;
        b[0] = a[0] - tr;
        b[1] = a[1] - ti;
        a[0] += tr;
        a[1] += ti;
      }
    }
  }
}
#endif

// ============================================================================
// Procesamiento: DC, ventana, FFT, PSD e impulsividad
// ============================================================================

void dsp_reiniciar(EstadoDsp& e) {
  memset(e.psd, 0, (e.N / 2 + 1) * sizeof(float));
  e.llenado = 0;
  e.marcos = e.muestras = 0;
  e.n_dif = 0;
  e.hay_previa = e.atipica_previa = false;
  e.mad_previa = -1;
  e.s2 = e.s4 = 0;
  e.n_d = e.eventos = 0;
}

void dsp_reiniciar_tiempos(EstadoDsp& e) { memset(e.t, 0, sizeof(e.t)); }

// Reserva los buffers para N; si algo falla conserva los anteriores y devuelve false.
bool dsp_configurar(EstadoDsp& e, int N) {
  if (N < N_MIN || N > N_MAX || (N & (N - 1))) return false;
  const size_t nb = N / 2 + 1;
  const size_t tam[] = {N * sizeof(float), N * sizeof(float), 2 * N * sizeof(float), nb * sizeof(float),
                        nb * sizeof(float), nb, N * sizeof(float), N * sizeof(float)};
  void* p[8];
  size_t total = 0;
  for (int i = 0; i < 8; ++i) {
    p[i] = reservar(tam[i]);
    total += tam[i];
    if (!p[i]) {
      while (i--) liberar(p[i]);
      return false;
    }
  }
  void* viejos[] = {e.ventana, e.marco, e.fft, e.psd, e.db, e.mascara, e.dif, e.trabajo};
  for (void* v : viejos)
    if (v) liberar(v);
  e.ventana = (float*)p[0];
  e.marco = (float*)p[1];
  e.fft = (float*)p[2];
  e.psd = (float*)p[3];
  e.db = (float*)p[4];
  e.mascara = (uint8_t*)p[5];
  e.dif = (float*)p[6];
  e.trabajo = (float*)p[7];
  e.bytes = total;
  e.N = N;
  // Periódica (no simétrica): w[n] = 0.5 - 0.5 cos(2 pi n / N), igual a get_window('hann', N).
  // dsps_wind_hann_f32 de esp-dsp usa N-1 en el denominador, por eso no se usa.
  for (int n = 0; n < N; ++n) e.ventana[n] = (float)(0.5 - 0.5 * cos(2 * M_PI * n / N));
  dsp_reiniciar(e);
  return true;
}

// Quita la media de x[0..N), aplica la ventana y deja la FFT en e.fft (sin normalizar).
void dsp_fft_bloque(EstadoDsp& e, const float* x) {
  const int N = e.N;
  const int64_t t0 = micros64();
  float media = 0;
  for (int n = 0; n < N; ++n) media += x[n];
  media /= N;
  for (int n = 0; n < N; ++n) {
    e.fft[2 * n] = (x[n] - media) * e.ventana[n];
    e.fft[2 * n + 1] = 0;
  }
  const int64_t t1 = micros64();
  fft_compleja(e.fft, N);
  e.t[ETAPA_DC_VENTANA].registrar(t1 - t0);
  e.t[ETAPA_FFT].registrar(micros64() - t1);
}

// Mediana exacta de v[0..n) (promedio de los dos centrales si n es par); desordena v.
float mediana(float* v, int n) {
  std::nth_element(v, v + n / 2, v + n);
  const float alta = v[n / 2];
  return n % 2 ? alta : 0.5f * (alta + *std::max_element(v, v + n / 2));
}

// Igual que medir_impulsividad de Python, pero con mediana y MAD por trozo de N muestras
// en vez de sobre todo el periodo: no hace falta guardar el periodo completo en RAM.
void procesar_trozo(EstadoDsp& e, const ConfigNodo1& c) {
  const int n = e.n_dif;
  if (!n) return;
  const int64_t t0 = micros64();
  // Un trozo corto (final del periodo) usa la escala del anterior: su mediana es poco fiable.
  if (n >= e.N / 2 || e.mad_previa < 0) {
    memcpy(e.trabajo, e.dif, n * sizeof(float));
    e.mediana_previa = mediana(e.trabajo, n);
    for (int i = 0; i < n; ++i) e.trabajo[i] = fabsf(e.dif[i] - e.mediana_previa);
    e.mad_previa = mediana(e.trabajo, n) / 0.6745f;
  }
  const float limite = c.k_atipicas_mad * std::max(e.mad_previa, FLT_MIN);
  for (int i = 0; i < n; ++i) {
    const double d = e.dif[i] - e.mediana_previa, d2 = d * d;
    e.s2 += d2;
    e.s4 += d2 * d2;
    const bool atipica = fabs(d) > limite;
    if (atipica && !e.atipica_previa) ++e.eventos;  // un evento = grupo de muestras atípicas
    e.atipica_previa = atipica;
  }
  e.n_d += n;
  e.n_dif = 0;
  e.t[ETAPA_IMPULSOS].registrar(micros64() - t0);
}

// Agrega una muestra; cada N/2 muestras cierra un marco y acumula su |X|^2 en la PSD.
void dsp_muestra(EstadoDsp& e, const ConfigNodo1& c, float x) {
  if (e.hay_previa) {
    e.dif[e.n_dif++] = x - e.previa;
    if (e.n_dif == e.N) procesar_trozo(e, c);
  }
  e.previa = x;
  e.hay_previa = true;
  ++e.muestras;
  e.marco[e.llenado++] = x;
  if (e.llenado < e.N) return;

  dsp_fft_bloque(e, e.marco);
  const int64_t t0 = micros64();
  for (int k = 0; k <= e.N / 2; ++k) e.psd[k] += e.fft[2 * k] * e.fft[2 * k] + e.fft[2 * k + 1] * e.fft[2 * k + 1];
  ++e.marcos;
  // Solapamiento del 50 %: la segunda mitad del marco inicia el siguiente.
  memmove(e.marco, e.marco + e.N / 2, (e.N / 2) * sizeof(float));
  e.llenado = e.N / 2;
  e.t[ETAPA_PSD].registrar(micros64() - t0);
}

// ============================================================================
// Diagnóstico (src/diagnostico.py: diagnosticar)
// ============================================================================

// Frecuencia del pico con interpolación parabólica sobre dB, ancho y potencia de [k0, k1].
Region describir_region(int k0, int k1, const float* P, const float* db, int nb, float df, const ConfigNodo1& c) {
  int k = k0;
  for (int i = k0 + 1; i <= k1; ++i)
    if (P[i] > P[k]) k = i;
  float delta = 0;
  if (k > 0 && k < nb - 1) {
    const float a = db[k - 1], b = db[k], cc = db[k + 1], den = a - 2 * b + cc;
    if (den < 0) delta = std::min(0.5f, std::max(-0.5f, 0.5f * (a - cc) / den));
  }
  Region r;
  r.f_lo = k0 * df;
  r.f_hi = k1 * df;
  r.f_pico = (k + delta) * df;
  r.ancho = (k1 - k0 + 1) * df;
  r.nivel_db = db[k];
  r.potencia = 0;
  for (int i = k0; i <= k1; ++i) r.potencia += P[i];
  r.k = k;
  r.linea = r.ancho <= c.ancho_linea_hz;
  r.red = false;
  return r;
}

// Máximos locales (±2 bins) sobre el umbral: los armónicos de red están a ~3 bins entre sí
// y el umbral de ocupación los fusionaría en una sola región.
int picos_locales(const float* P, const float* db, float max_db, int nb, float df, const ConfigNodo1& c) {
  int n = 0;
  for (int k = 2; k < nb - 2 && n < MAX_PICOS; ++k) {
    if (db[k] - max_db <= -c.umbral_ocupacion_db || P[k] <= P[k - 1]) continue;
    if (P[k] < std::max(std::max(P[k - 2], P[k - 1]), std::max(P[k + 1], P[k + 2]))) continue;
    picos[n++] = {k, describir_region(k, k, P, db, nb, df, c).f_pico};
  }
  return n;
}

// Familia 50/60 Hz con al menos armonicos_red_min armónicos distintos. Devuelve f0 o 0.
float buscar_red(int n_picos, const ConfigNodo1& c, int* elegido) {
  float mejor_f0 = 0;
  int mejor = 0;
  const int max_h = std::min(c.max_armonico_red, MAX_ARMONICO);
  for (int r = 0; r < MAX_RED; ++r) {
    const float f0 = c.frecuencias_red_hz[r];
    if (f0 <= 0) continue;
    int coincide[MAX_ARMONICO + 1];
    std::fill(coincide, coincide + MAX_ARMONICO + 1, -1);
    for (int p = 0; p < n_picos; ++p) {
      const long h = lrintf(picos[p].f / f0);  // redondeo al par, como round() de Python
      if (h >= 1 && h <= max_h && fabsf(picos[p].f - h * f0) <= c.tolerancia_red_hz) coincide[h] = p;
    }
    const int cuenta = (int)std::count_if(coincide + 1, coincide + max_h + 1, [](int i) { return i >= 0; });
    if (cuenta >= c.armonicos_red_min && cuenta > mejor) {
      mejor = cuenta;
      mejor_f0 = f0;
      std::copy(coincide, coincide + MAX_ARMONICO + 1, elegido);
    }
  }
  return mejor_f0;
}

void agregar(Region* lista, int& n, const Region& r, bool& truncado) {
  if (n < MAX_REGIONES) lista[n++] = r;
  else truncado = true;
}

// Diagnóstico de lo acumulado en el periodo. Devuelve false si no hay ningún marco completo.
bool diagnosticar(EstadoDsp& e, const ConfigNodo1& c, Diagnostico& d) {
  procesar_trozo(e, c);  // la diferencia pendiente del último trozo
  if (!e.marcos) return false;
  const int64_t t0 = micros64();
  const int nb = e.N / 2 + 1;
  const float df = c.fs_hz / e.N;
  float* P = e.psd;
  float* db = e.db;
  uint8_t* mascara = e.mascara;
  d.truncado = false;
  d.muestras = e.muestras;
  d.marcos = e.marcos;

  float max_db = -INFINITY;
  for (int k = 0; k < nb; ++k) {
    P[k] /= e.marcos;
    db[k] = 10 * log10f(std::max(P[k], FLT_MIN));
    max_db = std::max(max_db, db[k]);
  }
  for (int k = 0; k < nb; ++k) mascara[k] = db[k] - max_db > -c.umbral_ocupacion_db;
  mascara[0] = mascara[1] = 0;  // DC y su fuga: la media ya se eliminó.

  const double m2 = e.n_d ? e.s2 / e.n_d : 0;
  d.curtosis = m2 > 0 ? (float)(e.s4 / e.n_d / (m2 * m2) - 3) : 0;
  d.impulsivo = d.curtosis > c.umbral_curtosis;
  d.impulsos_por_s = d.impulsivo ? e.eventos / (e.muestras / c.fs_hz) : NAN;

  // Los armónicos de red se retiran de la máscara (con sus lóbulos) antes de formar regiones.
  int n_red = 0, elegido[MAX_ARMONICO + 1];
  d.frecuencia_red_hz = buscar_red(picos_locales(P, db, max_db, nb, df, c), c, elegido);
  if (d.frecuencia_red_hz > 0) {
    for (int h = 1; h <= MAX_ARMONICO; ++h) {
      if (elegido[h] < 0) continue;
      const int k = picos[elegido[h]].k;
      red[n_red] = describir_region(k, k, P, db, nb, df, c);
      red[n_red++].red = true;
      for (int i = std::max(0, k - 4); i <= std::min(nb - 1, k + 4); ++i) mascara[i] = 0;
    }
    std::sort(red, red + n_red, [](const Region& a, const Region& b) { return a.f_pico < b.f_pico; });
  } else {
    d.frecuencia_red_hz = NAN;
  }

  // Regiones ocupadas; se fusionan las separadas por <= hueco_fusion_bins bins.
  d.n_regiones = 0;
  for (int k = 0, inicio = -1, ultimo = -1; k <= nb; ++k) {
    const bool ocupado = k < nb && mascara[k];
    if (ocupado && inicio >= 0 && k - ultimo <= c.hueco_fusion_bins + 1) {
      ultimo = k;
    } else if (ocupado || k == nb) {
      if (inicio >= 0) agregar(d.regiones, d.n_regiones, describir_region(inicio, ultimo, P, db, nb, df, c), d.truncado);
      inicio = ultimo = k;
    }
  }

  // Bloque útil: desde la primera región hasta el primer hueco >= hueco_util_hz.
  int n_bloque = d.n_regiones ? 1 : 0;
  while (n_bloque < d.n_regiones &&
         d.regiones[n_bloque].f_lo - d.regiones[n_bloque - 1].f_hi <= c.hueco_util_hz)
    ++n_bloque;
  const float casi_todo = 0.8f * c.fs_hz / 2;
  // Con ruido impulsivo, un piso plano ocupa todo el espectro: no es una banda de ruido.
  auto conserva = [&](const Region& r) { return !d.impulsivo || r.ancho < casi_todo; };
  int nbq = 0;
  d.n_interferencias = 0;
  for (int i = 0; i < d.n_regiones; ++i) {
    if (!conserva(d.regiones[i])) continue;
    if (i < n_bloque) bloque[nbq++] = d.regiones[i];
    else agregar(d.interferencias, d.n_interferencias, d.regiones[i], d.truncado);
  }
  for (int i = 0; i < n_red; ++i) agregar(d.interferencias, d.n_interferencias, red[i], d.truncado);

  d.senal_banda_ancha = d.solapamiento = false;
  for (int i = 0; i < nbq; ++i) {
    if (bloque[i].linea) continue;
    if (bloque[i].f_lo <= c.ancho_dc_hz) d.senal_banda_ancha = true;
    else d.solapamiento = true;
  }
  const Region* banda = nullptr;  // la banda más ancha: interferencias primero, luego bloque
  d.tipos = 0;
  d.n_lineas = 0;
  float p_ruido = 0, p_util = 0;
  for (int i = 0; i < d.n_interferencias; ++i) {
    const Region& r = d.interferencias[i];
    p_ruido += r.potencia;
    if (r.linea) {
      d.lineas_hz[d.n_lineas++] = r.f_pico;
      if (!r.red) d.tipos |= TIPO_TONAL;
    } else {
      d.tipos |= TIPO_BANDA;
      if (!banda || r.ancho > banda->ancho) banda = &r;
    }
  }
  for (int i = 0; i < nbq; ++i) {
    p_util += bloque[i].potencia;
    if (!bloque[i].linea && bloque[i].f_lo > c.ancho_dc_hz && (!banda || bloque[i].ancho > banda->ancho))
      banda = &bloque[i];
  }
  std::sort(d.lineas_hz, d.lineas_hz + d.n_lineas);
  if (d.impulsivo) d.tipos |= TIPO_IMPULSIVO;
  if (n_red) d.tipos |= TIPO_RED;
  if (d.solapamiento) d.tipos |= TIPO_BANDA;

  d.confiable = nbq && !d.solapamiento && !d.senal_banda_ancha && !d.impulsivo;
  d.snr_estimada_db = d.confiable && p_ruido > 0 ? 10 * log10f(p_util / p_ruido) : NAN;
  d.banda_ruido_hz[0] = banda ? banda->f_lo : NAN;
  d.banda_ruido_hz[1] = banda ? banda->f_hi : NAN;
  d.bloque_util_hz[0] = nbq ? bloque[0].f_lo : NAN;
  d.bloque_util_hz[1] = nbq ? bloque[nbq - 1].f_hi : NAN;
  d.fin_banda_util_hz = d.confiable ? bloque[nbq - 1].f_hi + c.margen_banda_util_hz : NAN;

  if (d.confiable) d.motivo = "bloque útil separado del ruido por un hueco espectral";
  else if (d.impulsivo) d.motivo = "ruido impulsivo: espectro plano, la banda útil no es observable";
  else if (d.senal_banda_ancha) d.motivo = "señal de banda ancha desde DC: no se distingue del ruido de banda";
  else if (d.solapamiento) d.motivo = "ruido de banda superpuesto a la señal útil";
  else d.motivo = "no se encontró ninguna región ocupada";

  const int cuenta = __builtin_popcount(d.tipos);
  d.tipo = cuenta > 1 ? "mixto" : cuenta == 0 ? (d.confiable ? "ninguno" : "indeterminado")
                                                : NOMBRES_TIPO[__builtin_ctz(d.tipos)];
  ++d.numero;
  const int64_t dt = micros64() - t0;
  e.t[ETAPA_DIAGNOSTICO].registrar(dt);
  d.tiempo_ms = dt / 1000.0f;
  return true;
}

void lista_regiones(Escritor& w, const char* clave, const Region* r, int n) {
  w.add(",\"%s\":[", clave);  // [f_lo, f_hi, f_pico, nivel_db] por región
  for (int i = 0; i < n; ++i) {
    w.add(i ? ",[" : "[");
    w.num(r[i].f_lo);
    w.add(",");
    w.num(r[i].f_hi);
    w.add(",");
    w.num(r[i].f_pico);
    w.add(",");
    w.num(r[i].nivel_db);
    w.add("]");
  }
  w.add("]");
}

// JSON de una línea con las mismas claves que el diccionario de Python.
void diagnostico_json(const Diagnostico& d, Escritor& w) {
  w.add("{\"numero\":%lu,\"muestras\":%lu,\"fin_muestra\":%lu,\"marcos\":%lu,\"tipo\":\"%s\",\"tipos\":[",
        (unsigned long)d.numero, (unsigned long)d.muestras, (unsigned long)d.fin_muestra, (unsigned long)d.marcos, d.tipo);
  for (int i = 0, primero = 1; i < 4; ++i)
    if (d.tipos & (1 << i)) w.add(primero ? "\"%s\"" : ",\"%s\"", NOMBRES_TIPO[i]), primero = 0;
  w.add("],\"frecuencias_interferentes_hz\":[");
  for (int i = 0; i < d.n_lineas; ++i) {
    if (i) w.add(",");
    w.num(d.lineas_hz[i]);
  }
  w.add("],\"banda_ruido_hz\":");
  w.par(d.banda_ruido_hz[0], d.banda_ruido_hz[1]);
  w.add(",\"frecuencia_red_hz\":");
  w.num(d.frecuencia_red_hz);
  w.add(",\"fin_banda_util_hz\":");
  w.num(d.fin_banda_util_hz);
  w.add(",\"bloque_util_hz\":");
  w.par(d.bloque_util_hz[0], d.bloque_util_hz[1]);
  w.add(",\"solapamiento\":%s,\"senal_banda_ancha\":%s,\"confianza\":\"%s\",\"motivo\":\"%s\",\"snr_estimada_db\":",
        d.solapamiento ? "true" : "false", d.senal_banda_ancha ? "true" : "false", d.confiable ? "alta" : "baja",
        d.motivo);
  w.num(d.snr_estimada_db);
  w.add(",\"curtosis_diferencia\":");
  w.num(d.curtosis);
  w.add(",\"impulsos_por_s_estimados\":");
  w.num(d.impulsos_por_s);
  lista_regiones(w, "regiones", d.regiones, d.n_regiones);
  lista_regiones(w, "interferencias", d.interferencias, d.n_interferencias);
  w.add(",\"truncado\":%s,\"tiempo_calculo_ms\":%.3f}", d.truncado ? "true" : "false", d.tiempo_ms);
}

// ============================================================================
// Trama: CRC-32, armado y recepción
// ============================================================================

void poner16(uint8_t* p, uint16_t v) {  // little-endian, como el ESP32 y la PC
  p[0] = v;
  p[1] = v >> 8;
}
void poner32(uint8_t* p, uint32_t v) {
  poner16(p, v);
  poner16(p + 2, v >> 16);
}
void ponerf(uint8_t* p, float v) {
  uint32_t u;
  memcpy(&u, &v, 4);
  poner32(p, u);
}
uint16_t leer16(const uint8_t* p) { return p[0] | p[1] << 8; }
uint32_t leer32(const uint8_t* p) { return leer16(p) | (uint32_t)leer16(p + 2) << 16; }

// CRC-32 IEEE 802.3 (polinomio reflejado 0xEDB88320), el mismo de zlib.crc32 en Python.
uint32_t crc32(const uint8_t* p, size_t n) {
  if (!tabla_crc[1])
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      tabla_crc[i] = c;
    }
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < n; ++i) c = tabla_crc[(c ^ p[i]) & 0xFF] ^ (c >> 8);
  return ~c;
}

// Arma la trama en t y devuelve su longitud. Sin diagnóstico aún, los parámetros van en NAN.
// Con ref (n valores, REF_SIN donde no hay), la referencia viaja después de las muestras.
int armar_trama(uint8_t* t, const InfoBloque& b, const int16_t* m, int n, const Diagnostico& d, int n_fft,
                const int16_t* ref) {
  const bool hay = d.numero > 0;
  memset(t, 0, TRAMA_CABECERA);
  t[0] = TRAMA_SYNC0;
  t[1] = TRAMA_SYNC1;
  t[2] = TRAMA_VERSION;
  t[3] = TRAMA_CABECERA;
  poner32(t + 4, b.seq);
  poner16(t + 8, n);
  poner16(t + 10, b.estado | (ref ? EST_REF : 0));
  poner16(t + 12, b.recortadas);
  poner16(t + 14, b.atrasadas);
  poner32(t + 16, b.perdidos);
  ponerf(t + 20, b.fs_medida_hz);
  poner32(t + 24, d.numero);
  t[28] = hay ? d.tipos : 0;
  t[29] = hay ? d.confiable | d.solapamiento << 1 | d.senal_banda_ancha << 2 | d.impulsivo << 3 : 0;
  t[30] = hay ? std::min(d.n_lineas, MAX_LINEAS_TRAMA) : 0;
  ponerf(t + 32, hay ? d.fin_banda_util_hz : NAN);
  for (int i = 0; i < MAX_LINEAS_TRAMA; ++i) ponerf(t + 36 + 4 * i, i < t[30] ? d.lineas_hz[i] : NAN);
  ponerf(t + 52, hay ? d.banda_ruido_hz[0] : NAN);
  ponerf(t + 56, hay ? d.banda_ruido_hz[1] : NAN);
  ponerf(t + 60, hay ? d.frecuencia_red_hz : NAN);
  ponerf(t + 64, hay ? d.snr_estimada_db : NAN);
  poner16(t + 68, n_fft);
  poner16(t + 70, b.dc);
  poner32(t + 72, b.t_us);
  poner32(t + 76, hay ? d.fin_muestra : 0);  // muestras [fin - largo, fin) que cubrió el diagnóstico
  poner32(t + 80, hay ? d.muestras : 0);
  poner32(t + 84, b.hay_sync ? b.pos_ciclo : 0xFFFFFFFFu);
  poner16(t + 88, (uint16_t)(b.hay_sync ? b.inicio_ciclo : -1));
  t[90] = b.componente;
  t[91] = b.ref_estado;
  for (int i = 0; i < n; ++i) poner16(t + TRAMA_CABECERA + 2 * i, (uint16_t)m[i]);
  int largo = TRAMA_CABECERA + 2 * n;
  if (ref) {
    for (int i = 0; i < n; ++i) poner16(t + largo + 2 * i, (uint16_t)ref[i]);
    largo += 2 * n;
  }
  poner32(t + largo, crc32(t + 2, largo - 2));  // el CRC cubre todo menos el delimitador
  return largo + 4;
}

void receptor_reiniciar(Receptor& r) {
  r.n = r.esperado = 0;
  r.ok = r.errores_crc = r.perdidas = r.descartados = r.ultima_seq = 0;
  r.hay_seq = false;
}

// Recibe un byte; devuelve true cuando r.buf tiene una trama válida de r.esperado bytes.
// Ante basura o un CRC malo vuelve a buscar el delimitador desde el byte siguiente.
bool receptor_byte(Receptor& r, uint8_t b) {
  if (r.n == 1 && b != TRAMA_SYNC1) {
    ++r.descartados;
    r.n = 0;
  }
  if (r.n == 0) {
    if (b == TRAMA_SYNC0) r.buf[r.n++] = b;
    else ++r.descartados;
    return false;
  }
  r.buf[r.n++] = b;
  if (r.n == 4 && (r.buf[2] != TRAMA_VERSION || r.buf[3] != TRAMA_CABECERA)) {
    r.descartados += 4;
    r.n = 0;
    return false;
  }
  if (r.n == 10) {
    const int m = leer16(r.buf + 8);
    if (m == 0 || m > N_MAX) {
      r.descartados += 10;
      r.n = 0;
      return false;
    }
  }
  if (r.n == 12) {  // el estado dice si viaja la referencia
    const int m = leer16(r.buf + 8);
    r.esperado = TRAMA_CABECERA + 2 * m * (leer16(r.buf + 10) & EST_REF ? 2 : 1) + 4;
  }
  if (r.n < 12 || r.n < r.esperado) return false;
  r.n = 0;
  if (crc32(r.buf + 2, r.esperado - 6) != leer32(r.buf + r.esperado - 4)) {
    ++r.errores_crc;
    return false;
  }
  const uint32_t seq = leer32(r.buf + 4);
  if (r.hay_seq && seq != r.ultima_seq + 1) r.perdidas += seq - r.ultima_seq - 1;
  r.ultima_seq = seq;
  r.hay_seq = true;
  ++r.ok;
  return true;
}

// Bloque conocido para las pruebas de recepción: depende de la secuencia y de la posición.
// Las tramas impares llevan además una referencia conocida: el patrón con el signo cambiado.
int16_t patron(uint32_t seq, int i) { return (int16_t)((seq * 7u + i * 13u) & 0xFFF) - 2048; }

bool trama_es_patron(const uint8_t* t) {
  const uint32_t seq = leer32(t + 4);
  const int n = leer16(t + 8);
  const bool con_ref = leer16(t + 10) & EST_REF;
  if (con_ref != (seq % 2 == 1)) return false;
  for (int i = 0; i < n; ++i) {
    if ((int16_t)leer16(t + TRAMA_CABECERA + 2 * i) != patron(seq, i)) return false;
    if (con_ref && (int16_t)leer16(t + TRAMA_CABECERA + 2 * (n + i)) != -patron(seq, i)) return false;
  }
  return true;
}

void escribir_trama_hex(Nodo1& n, int largo) {
  Escritor w{salida, sizeof(salida), 0};
  w.add("TRAMA ");
  for (int i = 0; i < largo; ++i) {
    if (w.n > w.cap - 8) {  // una trama con referencia ocupa más que salida: se envía por partes
      n.escribir(salida);
      w.n = 0;
    }
    w.add("%02x", trama_tx[i]);
  }
  w.add("\n");
  n.escribir(salida);
}

int armar_trama_patron(Nodo1& n, uint32_t seq) {
  for (int i = 0; i < BLOQUE_ADC; ++i) {
    muestras_tx[i] = patron(seq, i);
    ref_tx[i] = -patron(seq, i);
  }
  const InfoBloque b{seq, EST_PRUEBA, 0, 0, 0, n.cfg.fs_hz, 0, seq * 64000u};
  return armar_trama(trama_tx, b, muestras_tx, BLOQUE_ADC, n.diag, n.dsp.N, seq % 2 ? ref_tx : nullptr);
}

// Diez tramas conocidas (las impares con referencia) por el receptor en memoria, con fallas inyectadas: la 3 con un bit
// alterado (CRC), la 5 no se envía (pérdida) y antes de la 7 llega basura con delimitadores
// falsos. Se esperan 8 tramas válidas con contenido correcto, 1 error de CRC y 2 pérdidas.
void prueba_trama(Nodo1& n) {
  static Receptor r;
  static const uint8_t basura[] = {0x00, 0xA5, 0x00, 0xA5, 0x5A, 0x07, 0x13, 0xFF, 0x5A, 0xA5};
  receptor_reiniciar(r);
  int contenido_ok = 0, largo = 0;
  int64_t armado_us = 0;
  for (uint32_t seq = 0; seq < 10; ++seq) {
    const int64_t t0 = micros64();
    largo = armar_trama_patron(n, seq);
    armado_us = std::max(armado_us, micros64() - t0);
    if (seq == 5) continue;
    if (seq == 3) trama_tx[TRAMA_CABECERA + 100] ^= 0x10;
    if (seq == 7)
      for (uint8_t x : basura) receptor_byte(r, x);
    for (int i = 0; i < largo; ++i)
      if (receptor_byte(r, trama_tx[i])) contenido_ok += trama_es_patron(r.buf);
  }
  const bool cumple = r.ok == 8 && contenido_ok == 8 && r.errores_crc == 1 && r.perdidas == 2;
  responder(n,
            "OK prueba_trama {\"validas\":%lu,\"contenido_ok\":%d,\"errores_crc\":%lu,\"perdidas\":%lu,"
            "\"bytes_descartados\":%lu,\"bytes_por_trama\":%d,\"armado_max_us\":%ld,\"cumple\":%s}\n",
            (unsigned long)r.ok, contenido_ok, (unsigned long)r.errores_crc, (unsigned long)r.perdidas,
            (unsigned long)r.descartados, largo, (long)armado_us, cumple ? "true" : "false");
}

float leerf(const uint8_t* p) {
  const uint32_t u = leer32(p);
  float v;
  memcpy(&v, &u, 4);
  return v;
}

// Texto legible de una trama YA ARMADA: se lee del mismo búfer que sale por la UART, así lo
// que se ve en el monitor es exactamente lo que reciben los nodos 2 y 3. Con "completa" se
// agregan las N muestras; si no, solo las 8 primeras.
void describir_trama(Nodo1& n, const uint8_t* t, bool completa) {
  static const char* const ESTADOS[] = {"recorte", "atraso", "perdida", "diag_nuevo", "fs_fuera", "prueba", "ref"};
  const int m = leer16(t + 8);
  const uint16_t estado = leer16(t + 10);
  const bool con_ref = estado & EST_REF;
  Escritor w{salida, sizeof(salida), 0};
  w.add("TX seq=%lu n=%d estado=[", (unsigned long)leer32(t + 4), m);
  for (int i = 0, primero = 1; i < 7; ++i)
    if (estado & (1 << i)) w.add(primero ? "%s" : ",%s", ESTADOS[i]), primero = 0;
  w.add("] recortadas=%u atrasadas=%u perdidos=%lu fs=%.1f dc=%u t_us=%lu", leer16(t + 12), leer16(t + 14),
        (unsigned long)leer32(t + 16), leerf(t + 20), leer16(t + 70), (unsigned long)leer32(t + 72));
  w.add(" | diag=%lu tipos=[", (unsigned long)leer32(t + 24));
  for (int i = 0, primero = 1; i < 4; ++i)
    if (t[28] & (1 << i)) w.add(primero ? "%s" : ",%s", NOMBRES_TIPO[i]), primero = 0;
  w.add("] confianza=%s fin_util=", t[29] & 1 ? "alta" : "baja");
  w.num(leerf(t + 32));
  w.add(" lineas=[");
  for (int i = 0; i < t[30]; ++i) {
    if (i) w.add(",");
    w.num(leerf(t + 36 + 4 * i));
  }
  w.add("] banda=");
  w.par(leerf(t + 52), leerf(t + 56));
  w.add(" red=");
  w.num(leerf(t + 60));
  w.add(" snr=");
  w.num(leerf(t + 64));
  w.add(" nfft=%u | ciclo pos=", leer16(t + 68));
  leer32(t + 84) == 0xFFFFFFFFu ? w.add("null") : w.add("%lu", (unsigned long)leer32(t + 84));
  w.add(" inicio=%d comp=%s ref=%s | x=", (int16_t)leer16(t + 88), NOMBRES_COMP[t[90] & 3], NOMBRES_REF[t[91] & 3]);
  for (int i = 0; i < (completa ? m : std::min(m, 8)); ++i) {
    if (w.n > w.cap - 64) {  // 1024 muestras no caben en salida: se envía por partes
      n.escribir(salida);
      w.n = 0;
    }
    w.add(i ? " %d" : "%d", (int16_t)leer16(t + TRAMA_CABECERA + 2 * i));
  }
  w.add(completa ? "" : " ...");
  if (con_ref) {
    w.add(" | r=");
    for (int i = 0; i < (completa ? m : std::min(m, 8)); ++i) {
      if (w.n > w.cap - 64) {
        n.escribir(salida);
        w.n = 0;
      }
      w.add(i ? " %d" : "%d", (int16_t)leer16(t + TRAMA_CABECERA + 2 * (m + i)));
    }
    w.add(completa ? "" : " ...");
  }
  const int largo = TRAMA_CABECERA + 2 * m * (con_ref ? 2 : 1);
  w.add(" | crc=0x%08lx bytes=%d\n", (unsigned long)leer32(t + largo), largo + 4);
  n.escribir(salida);
}

// Imprime k tramas conocidas en hexadecimal para validar el armado con un decodificador
// independiente en Python (validacion/validar_tramas.py).
void tramas_conocidas(Nodo1& n, int k) {
  for (int seq = 0; seq < k; ++seq) escribir_trama_hex(n, armar_trama_patron(n, seq));
  responder(n, "OK %d tramas\n", k);
}

// ============================================================================
// Sincronización con el emisor y referencia limpia
// ============================================================================

// 1, 2 y 3 ms del emisor son 16, 32 y 48 muestras; los cortes van a mitad de camino.
uint8_t clasificar_ancho(uint32_t alto) {
  if (alto < 8 || alto >= 64) return COMP_NINGUNA;  // no es un pulso del emisor
  return alto < 24 ? COMP_MEZCLA : alto < 40 ? COMP_LIMPIA : COMP_RUIDO;
}

// Una muestra del pin del pulso. Devuelve true si en esta muestra empieza un ciclo.
bool sync_muestra(Sincronia& s, bool nivel) {
  const bool sube = nivel && !s.nivel;
  if (s.nivel && !nivel) {
    s.ancho = s.alto;
    s.componente = clasificar_ancho(s.alto);
  }
  s.nivel = nivel;
  if (sube) {
    if (s.hay) s.periodo = s.pos + 1;
    s.hay = true;
    s.pos = 0;
    s.alto = 1;
    ++s.pulsos;
    return true;
  }
  if (nivel) ++s.alto;
  if (!s.hay) return false;
  ++s.pos;
  // Sin pulsos por más de dos periodos (o 10 s): el emisor está en silencio o se soltó el cable.
  if (s.pos > std::max<uint32_t>(2 * s.periodo, 160000)) {
    s.hay = false;
    s.periodo = 0;
    s.componente = COMP_NINGUNA;
  }
  return false;
}

// Se perdieron muestras: la posición en el ciclo ya no es confiable hasta el próximo pulso.
void sync_perdida(Sincronia& s) { s.hay = false; }

uint32_t diferencia(uint32_t a, uint32_t b) { return a > b ? a - b : b - a; }

// La referencia se aplica solo si el emisor sigue con el mismo periodo con que se capturó.
bool ref_aplica(const Referencia& r, const Sincronia& s) {
  return r.estado == REF_LISTA && s.hay && s.periodo && diferencia(s.periodo, r.periodo) <= REF_TOLERANCIA;
}

// Prepara la captura; empieza en el próximo pulso. Devuelve nullptr o el motivo del rechazo.
const char* ref_iniciar(Referencia& r, const Sincronia& s, int ciclos) {
  if (!s.hay || !s.periodo) return "no llegan pulsos de sincronizacion (GPIO35)";
  if (s.componente != COMP_LIMPIA) return "el emisor no esta en comp limpia (pulso de 2 ms)";
  r.estado = REF_ESPERANDO;
  r.periodo = s.periodo;
  r.largo = std::min<uint32_t>(s.periodo, REF_MAX);
  r.ciclos = ciclos;
  r.hechos = 0;
  r.motivo = nullptr;
  memset(r.datos, 0, r.largo * sizeof(int16_t));
  return nullptr;
}

void ref_cancelar(Referencia& r, const char* motivo) {
  if (r.estado == REF_ESPERANDO || r.estado == REF_CAPTURANDO) {
    r.estado = REF_VACIA;
    r.motivo = motivo;
  }
}

// Suma una muestra al ciclo; al cerrar el último ciclo divide entre los ciclos y la deja lista.
// Promediar K ciclos baja el ruido de la sala en la referencia en 10·log10(K) dB.
EventoRef ref_muestra(Referencia& r, const Sincronia& s, bool inicio, int16_t x) {
  if (r.estado == REF_ESPERANDO) {
    if (!inicio) return EV_NADA;
    r.estado = REF_CAPTURANDO;
  } else if (r.estado != REF_CAPTURANDO) {
    return EV_NADA;
  } else if (inicio) {
    if (diferencia(s.periodo, r.periodo) > REF_TOLERANCIA) {
      ref_cancelar(r, "ciclo irregular: el emisor cambio de senal o se perdio un pulso");
      return EV_CANCELADA;
    }
    if (s.componente != COMP_LIMPIA) {
      ref_cancelar(r, "el emisor dejo de emitir la limpia");
      return EV_CANCELADA;
    }
    if (++r.hechos == r.ciclos) {
      for (uint32_t i = 0; i < r.largo; ++i) r.datos[i] = (int16_t)lroundf((float)r.datos[i] / r.ciclos);
      r.estado = REF_LISTA;
      return EV_LISTA;
    }
  }
  if (s.pos < r.largo) r.datos[s.pos] += x;
  return EV_NADA;
}

// Recorre un bloque: sigue el pulso (bits: un bit por muestra, nullptr si no hay pin), captura
// la referencia y llena ref_out con la referencia de cada muestra (REF_SIN donde no hay).
// Devuelve true si alguna muestra del bloque tiene referencia.
bool sync_bloque(Nodo1& n, const uint8_t* bits, const int16_t* x, int m, InfoBloque& b, int16_t* ref_out,
                 EventoRef& evento) {
  bool alguna = false;
  b.inicio_ciclo = -1;
  for (int i = 0; i < m; ++i) {
    const bool inicio = bits && sync_muestra(n.sync, bits[i >> 3] >> (i & 7) & 1);
    if (i == 0) {
      b.hay_sync = n.sync.hay;
      b.pos_ciclo = n.sync.pos;
    }
    if (inicio && b.inicio_ciclo < 0) b.inicio_ciclo = i;
    const EventoRef e = ref_muestra(n.ref, n.sync, inicio, x[i]);
    if (e != EV_NADA) evento = e;
    const bool vale = ref_aplica(n.ref, n.sync) && n.sync.pos < n.ref.largo;
    ref_out[i] = vale ? n.ref.datos[n.sync.pos] : REF_SIN;
    alguna |= vale;
  }
  if (!b.hay_sync && n.sync.hay) {  // el primer pulso llegó dentro del bloque
    b.hay_sync = true;
    b.pos_ciclo = 0;
  }
  b.componente = n.sync.hay ? n.sync.componente : (uint8_t)COMP_NINGUNA;
  b.ref_estado = n.ref.estado;
  return alguna;
}

void mostrar_ref(Nodo1& n) {
  const Referencia& r = n.ref;
  const Sincronia& s = n.sync;
  double suma2 = 0;
  for (uint32_t i = 0; r.estado == REF_LISTA && i < r.largo; ++i) suma2 += (double)r.datos[i] * r.datos[i];
  responder(n,
            "REF {\"estado\":\"%s\",\"aplica\":%s,\"muestras\":%lu,\"ciclos\":%d,\"hechos\":%d,\"periodo_ref\":%lu,"
            "\"rms_codigos\":%.1f,\"sincronia\":%s,\"periodo_medido\":%lu,\"componente\":\"%s\","
            "\"ancho_pulso_muestras\":%lu,\"pulsos\":%lu,\"motivo\":%s%s%s}\n",
            NOMBRES_REF[r.estado], ref_aplica(r, s) ? "true" : "false", (unsigned long)r.largo, r.ciclos, r.hechos,
            (unsigned long)r.periodo, r.estado == REF_LISTA && r.largo ? sqrt(suma2 / r.largo) : 0.0,
            s.hay ? "true" : "false", (unsigned long)s.periodo, NOMBRES_COMP[s.componente], (unsigned long)s.ancho,
            (unsigned long)s.pulsos, r.motivo ? "\"" : "", r.motivo ? r.motivo : "null", r.motivo ? "\"" : "");
}

void comando_ref(Nodo1& n, const char* a1, const char* a2) {
  if (!a1) return mostrar_ref(n);
  if (!strcmp(a1, "borrar")) {
    n.ref.estado = REF_VACIA;
    n.ref.motivo = nullptr;
    return responder(n, "OK referencia borrada\n");
  }
  if (strcmp(a1, "capturar")) return responder(n, "ERR use: ref [capturar <ciclos 1..%d> | borrar]\n", REF_K_MAX);
  const int k = a2 ? atoi(a2) : REF_K_MAX;
  if (k < 1 || k > REF_K_MAX) return responder(n, "ERR ciclos entre 1 y %d\n", REF_K_MAX);
  if (const char* motivo = ref_iniciar(n.ref, n.sync, k)) return responder(n, "ERR ref: %s\n", motivo);
  responder(n, "OK ref esperando el proximo pulso: %d ciclos de %lu muestras\n", k, (unsigned long)n.ref.periodo);
}

// Verifica la sincronía y la referencia con una señal conocida, sin placa ni emisor:
// ciclo de P muestras, limpia periódica + "ruido de sala", pulsos de 2 ms mientras se captura la
// referencia y de 1 ms con la mezcla (limpia + interferencia). Compara la SNR medida con la
// referencia contra la real, comprueba que desplazar la referencia una muestra empeora el MSE,
// que la captura se cancela si el pulso no es de la limpia y que la trama lleve la referencia.
void prueba_ref(Nodo1& n) {
  constexpr int P = 4000, K = 8, CICLOS = 2 + K + 1 + 4;
  const Sincronia sync_antes = n.sync;
  const Referencia ref_antes = n.ref;
  n.sync = Sincronia{};
  n.ref.estado = REF_VACIA;
  uint32_t semilla = 777;
  auto sala = [&]() {
    semilla = semilla * 1664525u + 1013904223u;
    return (int)((semilla >> 16) % 81) - 40;  // ±40 códigos
  };
  auto limpia = [](long t) {
    const double ph = 2 * M_PI * (t % P) / P;
    return 1200 * sin(5 * ph) + 500 * sin(37 * ph + 0.4);
  };
  static int16_t x[BLOQUE_ADC];
  uint8_t bits[BLOQUE_ADC / 8];
  double s2 = 0, e2 = 0, d2 = 0, r2 = 0, e_ref2 = 0, n_ref = 0;
  bool lista = false, trama_ok = true, pedida = false;
  int tramas_con_ref = 0;
  Receptor rx;
  receptor_reiniciar(rx);
  for (long t0 = 0; t0 < (long)CICLOS * P; t0 += BLOQUE_ADC) {
    const bool mezcla = lista;
    memset(bits, 0, sizeof(bits));
    for (int i = 0; i < BLOQUE_ADC; ++i) {
      const long t = t0 + i;
      if (t % P < (mezcla ? 16 : 32)) bits[i >> 3] |= 1 << (i & 7);
      const double ruido = mezcla ? 700 * sin(2 * M_PI * 2508.0 * t / 16000) : 0;
      x[i] = (int16_t)lround(limpia(t) + ruido + sala());
    }
    InfoBloque b{(uint32_t)(t0 / BLOQUE_ADC), EST_PRUEBA, 0, 0, 0, n.cfg.fs_hz, 0, 0};
    EventoRef ev = EV_NADA;
    const bool con_ref = sync_bloque(n, bits, x, BLOQUE_ADC, b, ref_tx, ev);
    if (!pedida && n.sync.periodo && n.sync.componente == COMP_LIMPIA) pedida = !ref_iniciar(n.ref, n.sync, K);
    if (ev == EV_LISTA) lista = true;
    if (mezcla && con_ref) {
      // Error de la referencia contra la limpia ideal y SNR de entrada medida con ella.
      for (int i = 0; i < BLOQUE_ADC; ++i) {
        if (ref_tx[i] == REF_SIN) continue;
        const long t = t0 + i;
        const double s = limpia(t), y = x[i] - s;
        s2 += s * s;
        e2 += y * y;
        r2 += (double)ref_tx[i] * ref_tx[i];
        d2 += (double)(x[i] - ref_tx[i]) * (x[i] - ref_tx[i]);
        e_ref2 += (ref_tx[i] - s) * (ref_tx[i] - s);
        ++n_ref;
      }
      const int largo = armar_trama(trama_tx, b, x, BLOQUE_ADC, n.diag, n.dsp.N, ref_tx);
      bool recibida = false;
      for (int i = 0; i < largo; ++i) recibida |= receptor_byte(rx, trama_tx[i]);
      trama_ok &= recibida && (leer16(rx.buf + 10) & EST_REF) &&
                  !memcmp(rx.buf + TRAMA_CABECERA + 2 * BLOQUE_ADC, trama_tx + TRAMA_CABECERA + 2 * BLOQUE_ADC,
                          2 * BLOQUE_ADC);
      ++tramas_con_ref;
    }
  }
  // MSE con la referencia desplazada una muestra: debe ser mayor.
  double d2_desp = 0;
  for (uint32_t i = 1; lista && i < n.ref.largo; ++i) {
    const double y = limpia(i) - n.ref.datos[i - 1];
    d2_desp += y * y;
  }
  double d2_bien = 0;
  for (uint32_t i = 1; lista && i < n.ref.largo; ++i) {
    const double y = limpia(i) - n.ref.datos[i];
    d2_bien += y * y;
  }
  // Una captura nueva con pulsos de 1 ms (mezcla) debe rechazarse.
  const char* rechazo = ref_iniciar(n.ref, Sincronia{true, false, 0, 0, P, 16, 1, COMP_MEZCLA}, K);
  const double snr_real = 10 * log10(s2 / std::max(e2, 1e-9)), snr_medida = 10 * log10(r2 / std::max(d2, 1e-9));
  const double error_rms = n_ref ? sqrt(e_ref2 / n_ref) : NAN;
  const bool cumple = lista && fabs(snr_medida - snr_real) < 0.5 && d2_desp > 4 * d2_bien && rechazo && trama_ok &&
                      tramas_con_ref > 0 && error_rms < 40;
  responder(n,
            "OK prueba_ref {\"referencia_lista\":%s,\"muestras_ref\":%lu,\"error_ref_rms_codigos\":%.2f,"
            "\"ruido_sala_rms_codigos\":%.2f,\"snr_entrada_real_db\":%.3f,\"snr_entrada_medida_db\":%.3f,"
            "\"mse_desplazada_sobre_alineada\":%.1f,\"rechaza_si_no_es_limpia\":%s,\"tramas_con_ref\":%d,"
            "\"trama_ref_ok\":%s,\"cumple\":%s}\n",
            lista ? "true" : "false", (unsigned long)n.ref.largo, error_rms, 40 / sqrt(3.0), snr_real, snr_medida,
            d2_bien > 0 ? d2_desp / d2_bien : 0.0, rechazo ? "true" : "false", tramas_con_ref,
            trama_ok ? "true" : "false", cumple ? "true" : "false");
  n.sync = sync_antes;
  n.ref = ref_antes;
  if (ref_antes.estado != REF_VACIA) {  // la prueba usó el mismo búfer: lo guardado ya no vale
    n.ref.estado = REF_VACIA;
    n.ref.motivo = "borrada por prueba_ref";
  }
}

// ============================================================================
// Consola: comandos por línea y carga binaria de muestras
// Cada respuesta inicia con una etiqueta: OK, ERR, CFG, DIAG, FIN, TIEMPOS, MEM, FFT_X, FFT_OUT.
// ============================================================================

void responder(Nodo1& n, const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(salida, sizeof(salida), fmt, ap);
  va_end(ap);
  n.escribir(salida);
}

bool nodo1_iniciar(Nodo1& n) {
  // 64 KB en el heap: como arreglo estático no cabe en el segmento de datos del ESP32.
  if (!n.ref.datos) n.ref.datos = (int16_t*)reservar(REF_MAX * sizeof(int16_t));
  if (!n.ref.datos || !iniciar_fft() || !dsp_configurar(n.dsp, n.cfg.n_bloque)) return false;
  dsp_reiniciar_tiempos(n.dsp);
  return true;
}

// PSD promediada del periodo que se acaba de diagnosticar, en dB (10·log10 de |X|² medio, con
// las muestras normalizadas a 2048 códigos). La PC solo la grafica: el cálculo es del nodo.
// Formato: PSD <número de diagnóstico> <resolución en Hz> <N/2+1 valores>.
void emitir_espectro(Nodo1& n) {
  const EstadoDsp& e = n.dsp;
  Escritor w{salida, sizeof(salida), 0};
  w.add("PSD %lu %g", (unsigned long)n.diag.numero, n.cfg.fs_hz / e.N);
  for (int k = 0; k <= e.N / 2; ++k) {
    if (w.n > w.cap - 16) {  // con N = 2048 no cabe en salida: se envía por partes
      n.escribir(salida);
      w.n = 0;
    }
    w.add(" %.1f", e.db[k]);
  }
  w.add("\n");
  n.escribir(salida);
}

void emitir_diagnostico(Nodo1& n) {
  if (diagnosticar(n.dsp, n.cfg, n.diag)) {
    n.diag.fin_muestra = n.muestras_totales;
    Escritor w{salida, sizeof(salida), 0};
    w.add("DIAG ");
    diagnostico_json(n.diag, w);
    w.add("\n");
    n.escribir(salida);
    if (n.enviar_espectro) emitir_espectro(n);
  } else {
    responder(n, "ERR sin marcos completos: se necesitan al menos %d muestras\n", n.dsp.N);
  }
  dsp_reiniciar(n.dsp);
}

void alimentar(Nodo1& n, const float* x, size_t cuantas, bool periodico) {
  const uint32_t objetivo = (uint32_t)lroundf(n.cfg.periodo_diag_ms * n.cfg.fs_hz / 1000);
  for (size_t i = 0; i < cuantas; ++i) {
    dsp_muestra(n.dsp, n.cfg, x[i]);
    ++n.muestras_totales;
    if (periodico && objetivo && n.dsp.muestras >= objetivo) emitir_diagnostico(n);
  }
}

// Punto de entrada de las muestras del ADC (o de la fuente de prueba). Diagnostica cada periodo.
void nodo1_alimentar(Nodo1& n, const float* x, size_t cuantas) {
  if (!n.binario_pendiente) alimentar(n, x, cuantas, true);  // durante una carga se ignora la fuente
}

float leer_parametro(const ConfigNodo1& c, const Parametro& p) {
  const char* base = (const char*)&c + p.desplazamiento;
  return p.entero ? *(const int*)base : *(const float*)base;
}

void mostrar_config(Nodo1& n) {
  Escritor w{salida, sizeof(salida), 0};
  w.add("CFG {");
  for (int i = 0; i < N_PARAMETROS; ++i)
    w.add("%s\"%s\":%g", i ? "," : "", PARAMETROS[i].clave, leer_parametro(n.cfg, PARAMETROS[i]));
  w.add(",\"resolucion_hz\":%g}\n", n.cfg.fs_hz / n.dsp.N);
  n.escribir(salida);
}

void cambiar_parametro(Nodo1& n, const char* clave, const char* valor) {
  int i = 0;
  while (i < N_PARAMETROS && strcmp(clave, PARAMETROS[i].clave) &&
         !(PARAMETROS[i].alias && !strcmp(clave, PARAMETROS[i].alias)))
    ++i;
  if (i == N_PARAMETROS) return responder(n, "ERR clave desconocida: %s (use cfg)\n", clave);
  const Parametro& p = PARAMETROS[i];
  char* fin = nullptr;
  const float v = valor ? strtof(valor, &fin) : NAN;
  if (!valor || *fin || !(v >= p.minimo && v <= p.maximo) || (p.entero && v != floorf(v)))
    return responder(n, "ERR %s fuera de rango [%g, %g]\n", p.clave, p.minimo, p.maximo);
  if (i == I_N) {  // reserva buffers nuevos
    if (!dsp_configurar(n.dsp, (int)v)) return responder(n, "ERR N debe ser potencia de dos y caber en RAM\n");
    dsp_reiniciar_tiempos(n.dsp);
  }
  char* base = (char*)&n.cfg + p.desplazamiento;
  if (p.entero) *(int*)base = (int)v;
  else *(float*)base = v;
  if (i == I_FS) dsp_reiniciar(n.dsp);  // fs cambia la escala de frecuencias
  responder(n, "OK %s=%g\n", p.clave, v);
}

void mostrar_tiempos(Nodo1& n) {
  const EstadoDsp& e = n.dsp;
  Escritor w{salida, sizeof(salida), 0};
  w.add("TIEMPOS {\"n_bloque\":%d", e.N);
  double media[N_ETAPAS];
  for (int i = 0; i < N_ETAPAS; ++i) {
    const Cronometro& c = e.t[i];
    media[i] = c.n ? (double)c.total_us / c.n : 0;
    w.add(",\"%s\":{\"n\":%lu,\"media_us\":%.1f,\"max_us\":%ld,\"ultimo_us\":%ld}", NOMBRES_ETAPA[i],
          (unsigned long)c.n, media[i], (long)c.max_us, (long)c.ultimo_us);
  }
  // Carga en tiempo real: fs/(N/2) marcos/s, fs/N trozos de impulsos/s y un diagnóstico por periodo.
  const double fs = n.cfg.fs_hz;
  const double us_por_s = (media[ETAPA_DC_VENTANA] + media[ETAPA_FFT] + media[ETAPA_PSD]) * fs / (e.N / 2) +
                          media[ETAPA_IMPULSOS] * fs / e.N +
                          (n.cfg.periodo_diag_ms > 0 ? media[ETAPA_DIAGNOSTICO] * 1000 / n.cfg.periodo_diag_ms : 0);
  w.add(",\"presupuesto_marco_us\":%.0f,\"carga_cpu_pct\":%.2f,\"latencia_diagnostico_ms\":%.1f}\n",
        1e6 * (e.N / 2) / fs, us_por_s / 1e4, n.cfg.periodo_diag_ms + media[ETAPA_DIAGNOSTICO] / 1000);
  n.escribir(salida);
}

void mostrar_memoria(Nodo1& n) {
  Escritor w{salida, sizeof(salida), 0};
  w.add("MEM {\"n_bloque\":%d,\"bytes_buffers_dsp\":%u,\"bytes_estado_nodo1\":%u,\"bytes_estaticos_diagnostico\":%u,"
        "\"bytes_referencia\":%u",
        n.dsp.N, (unsigned)n.dsp.bytes, (unsigned)sizeof(Nodo1),
        (unsigned)(sizeof(picos) + sizeof(red) + sizeof(bloque)), (unsigned)(REF_MAX * sizeof(int16_t)));
  if (n.memoria_plataforma) w.n = std::min(w.cap - 1, w.n + n.memoria_plataforma(salida + w.n, w.cap - w.n));
  w.add("}\n");
  n.escribir(salida);
}

// Vector determinista (dos tonos, uno fuera de bin, DC y ruido LCG) o, con "adc", el último
// bloque capturado. Se imprime la entrada cruda y la salida compleja; validar_fft.py repite
// DC + Hann + FFT en NumPy y compara.
void prueba_fft(Nodo1& n, bool real) {
  EstadoDsp& e = n.dsp;
  float* x = e.trabajo;  // libre fuera de procesar_trozo
  if (real && (!n.bloque_real || e.N > BLOQUE_ADC))
    return responder(n, "ERR no hay bloque del ADC de %d muestras\n", e.N);
  if (real) memcpy(x, n.bloque_real, e.N * sizeof(float));
  uint32_t semilla = 12345;
  for (int i = 0; i < e.N && !real; ++i) {
    semilla = semilla * 1664525u + 1013904223u;
    const float ruido = (semilla >> 8) / 8388608.0f - 1;
    x[i] = 0.3f + 0.7f * sinf(2 * (float)M_PI * 1000 * i / n.cfg.fs_hz) +
           0.25f * sinf(2 * (float)M_PI * 2508 * i / n.cfg.fs_hz + 0.5f) + 0.05f * ruido;
  }
  n.escribir("FFT_X");
  for (int i = 0; i < e.N; ++i) responder(n, " %.9g", x[i]);
  dsp_fft_bloque(e, x);
  n.escribir("\nFFT_OUT");
  for (int i = 0; i < 2 * e.N; ++i) responder(n, " %.9g", e.fft[i]);
  responder(n, "\nOK fft N=%d dc_ventana_us=%ld fft_us=%ld\n", e.N, (long)e.t[ETAPA_DC_VENTANA].ultimo_us,
            (long)e.t[ETAPA_FFT].ultimo_us);
}

const char AYUDA[] =
    "OK comandos:\n"
    "  cfg                      parametros actuales\n"
    "  set <clave> <valor>      cambia un parametro (alias: n, periodo, umbral, curtosis, kmad)\n"
    "  diag                     diagnostica ya con lo acumulado\n"
    "  reiniciar                descarta lo acumulado del periodo\n"
    "  muestras <L> [periodico] [tramas]  siguen L float32 little-endian; DIAG, TRAMA y FIN\n"
    "  fft_prueba [adc]         FFT_X y FFT_OUT de un vector fijo o del ultimo bloque del ADC\n"
    "  tiempos [reiniciar]      tiempo por etapa y carga de CPU\n"
    "  mem                      memoria usada\n"
    "  espectro <on|off>        linea PSD (dB) despues de cada DIAG, para graficar en vivo\n"
    "  trama                    ultima trama enviada, legible y con todas sus muestras\n"
    "  prueba_trama             armado y recepcion de 10 tramas con fallas inyectadas\n"
    "  tramas_conocidas <k>     imprime k tramas de prueba en hexadecimal (TRAMA ...)\n"
    "  ref [capturar <k> | borrar]  referencia limpia: estado, capturar k ciclos (emisor en comp limpia)\n"
    "  prueba_ref               sincronia y referencia con una senal conocida\n"
#ifdef ARDUINO
    "  fuente <adc|sint|patron|nada>  origen de las muestras (por defecto adc)\n"
    "  interferencia <hz>       tono interferente de la fuente sint\n"
    "  adc                      estado de la captura: fs medida, perdidas, recortes, UART\n"
    "  tramas <on|off>          envio de tramas por UART2\n"
    "  tramas_usb <on|off>      copia de cada trama por este puerto USB, para capturar sin adaptador\n"
    "  ver <on|off>             muestra en este monitor cada trama que sale por GPIO17\n"
    "  rx [reiniciar]           tramas recibidas por UART2 (lazo GPIO17 -> GPIO16)\n"
#endif
    ;

void ejecutar(Nodo1& n, char* linea) {
  char* cmd = strtok(linea, " \t");
  char* a1 = strtok(nullptr, " \t");
  char* a2 = strtok(nullptr, " \t");
  char* a3 = strtok(nullptr, " \t");
  if (!cmd) return;
  if (!strcmp(cmd, "?") || !strcmp(cmd, "ayuda")) {
    n.escribir(AYUDA);
  } else if (!strcmp(cmd, "cfg")) {
    mostrar_config(n);
  } else if (!strcmp(cmd, "set") && a1) {
    cambiar_parametro(n, a1, a2);
  } else if (!strcmp(cmd, "diag")) {
    emitir_diagnostico(n);
  } else if (!strcmp(cmd, "reiniciar")) {
    dsp_reiniciar(n.dsp);
    n.escribir("OK reiniciado\n");
  } else if (!strcmp(cmd, "tiempos") && a1 && !strcmp(a1, "reiniciar")) {
    dsp_reiniciar_tiempos(n.dsp);
    n.escribir("OK\n");
  } else if (!strcmp(cmd, "tiempos")) {
    mostrar_tiempos(n);
  } else if (!strcmp(cmd, "mem")) {
    mostrar_memoria(n);
  } else if (!strcmp(cmd, "espectro") && a1 && (!strcmp(a1, "on") || !strcmp(a1, "off"))) {
    n.enviar_espectro = !strcmp(a1, "on");
    responder(n, "OK espectro %s\n", a1);
  } else if (!strcmp(cmd, "fft_prueba")) {
    prueba_fft(n, a1 && !strcmp(a1, "adc"));
  } else if (!strcmp(cmd, "trama")) {
    if (trama_tx[0] == TRAMA_SYNC0) describir_trama(n, trama_tx, true);
    else n.escribir("ERR todavía no se armó ninguna trama\n");
  } else if (!strcmp(cmd, "prueba_trama")) {
    prueba_trama(n);
  } else if (!strcmp(cmd, "ref")) {
    comando_ref(n, a1, a2);
  } else if (!strcmp(cmd, "prueba_ref")) {
    prueba_ref(n);
  } else if (!strcmp(cmd, "tramas_conocidas") && a1 && atoi(a1) > 0 && atoi(a1) <= 100) {
    tramas_conocidas(n, atoi(a1));
  } else if (!strcmp(cmd, "muestras") && a1 && atol(a1) > 0) {
    dsp_reiniciar(n.dsp);
    n.binario_pendiente = (uint32_t)atol(a1);
    auto opcion = [&](const char* o) { return (a2 && !strcmp(a2, o)) || (a3 && !strcmp(a3, o)); };
    n.binario_periodico = opcion("periodico");
    n.binario_tramas = opcion("tramas");
    n.n_parcial = n.llenado_trama = 0;
    n.seq_trama = n.muestras_totales = 0;
    responder(n, "OK esperando %lu muestras\n", (unsigned long)n.binario_pendiente);
  } else if (!n.comando_plataforma || !n.comando_plataforma(cmd, a1)) {
    responder(n, "ERR comando desconocido: %s (use ?)\n", cmd);
  }
}

// Bytes recibidos por la consola: líneas de texto o la carga binaria de "muestras".
void nodo1_bytes(Nodo1& n, const uint8_t* b, size_t cuantos) {
  for (size_t i = 0; i < cuantos; ++i) {
    if (n.binario_pendiente) {
      n.parcial[n.n_parcial++] = b[i];
      if (n.n_parcial < 4) continue;
      float x;
      memcpy(&x, n.parcial, 4);  // ESP32 y PC son little-endian
      n.n_parcial = 0;
      if (n.binario_tramas) {  // como la captura: int16 en unidades del ADC (escala 2048) y una trama por bloque
        const int16_t q = (int16_t)std::min(32767L, std::max(-32768L, lroundf(x * 2048)));
        muestras_tx[n.llenado_trama++] = q;
        x = q / 2048.0f;
      }
      alimentar(n, &x, 1, n.binario_periodico);
      if (n.binario_tramas && n.llenado_trama == BLOQUE_ADC) {
        const InfoBloque b{n.seq_trama, EST_PRUEBA, 0, 0, 0, n.cfg.fs_hz, 0, n.seq_trama * 64000u};
        ++n.seq_trama;
        n.llenado_trama = 0;
        escribir_trama_hex(n, armar_trama(trama_tx, b, muestras_tx, BLOQUE_ADC, n.diag, n.dsp.N, nullptr));
      }
      if (--n.binario_pendiente) continue;
      if (!n.binario_periodico) emitir_diagnostico(n);
      dsp_reiniciar(n.dsp);  // en modo periódico se descarta el resto incompleto
      n.escribir("FIN\n");
    } else if (b[i] == '\n') {
      n.linea[n.n_linea] = 0;
      n.n_linea = 0;
      ejecutar(n, n.linea);
    } else if (b[i] != '\r' && n.n_linea < (int)sizeof(n.linea) - 1) {
      n.linea[n.n_linea++] = b[i];
    }
  }
}

// ============================================================================
// Arduino: captura por ADC, tramas por UART2, consola por USB
// ============================================================================
#ifdef ARDUINO

constexpr int PIN_ADC = 34;                   // ADC1_CH6, solo entrada. ADC2 no: choca con el WiFi
constexpr adc_channel_t CANAL_ADC = ADC_CHANNEL_6;
constexpr int PIN_TRAMA_RX = 16, PIN_TRAMA_TX = 17;  // UART2 hacia los nodos 2 y 3
constexpr int PIN_SYNC = 35;                  // pulso del emisor (su GPIO27); solo entrada, sin pull interno
constexpr uint32_t BAUDIOS_TRAMA = 921600;    // 2144 B cada 64 ms = 335 kbaud (36 %); con referencia 4192 B (71 %)
constexpr uint32_t FS_ADC = 16000;
constexpr uint32_t RELOJ_TIMER_HZ = 2000000;  // 2 MHz / 125 = 16 kHz exactos (62.5 us)
constexpr float TOLERANCIA_FS = 0.005f;
constexpr float ALFA_DC = 1.0f / 8192;        // seguidor de DC: constante de 0.5 s, corte de 0.3 Hz

// Productor: la ISR del temporizador despierta a tarea_adc, que lee el ADC y llena el doble búfer.
static adc_oneshot_unit_handle_t adc_unidad;
static adc_cali_handle_t adc_cali;            // nullptr si no se pudo calibrar
static TaskHandle_t tarea_adc_h;
static QueueHandle_t cola_bloques;
static uint16_t buf_adc[2][BLOQUE_ADC];
static uint8_t buf_sync[2][BLOQUE_ADC / 8];    // nivel del pin del pulso, un bit por muestra
static std::atomic<bool> ocupado[2];          // true mientras loop() procesa ese búfer
static std::atomic<uint32_t> adc_seq, adc_perdidos, adc_atrasadas, adc_recortadas;
static std::atomic<int32_t> adc_lectura_max_us;
// Retardo entre la alarma del temporizador y la lectura del ADC. Su variación es el jitter del
// instante de muestreo: 1 µs de jitter limita la SNR a ≈ 36 dB en 2508 Hz. Resolución: 1 µs.
static volatile uint32_t t_alarma_us;         // la escribe la ISR (32 bits: escritura atómica)
struct Jitter {
  uint32_t n, max_us;
  uint64_t suma, suma2;
};
static Jitter jitter_publicado;               // copia que lee loop(), bajo mux_jitter
static portMUX_TYPE mux_jitter = portMUX_INITIALIZER_UNLOCKED;
static std::atomic<bool> jitter_reiniciar;

// Consumidor (loop): procesa, diagnostica y envía.
static Fuente fuente = FUENTE_ADC;
static bool tramas_activas = true;
static bool ver_tramas = false;               // eco legible de cada trama en la consola USB
static bool tramas_usb = false;               // copia binaria de cada trama por la consola USB
static uint32_t tramas_usb_enviadas, tramas_usb_descartadas;
static int ultimo_largo = TRAMA_CABECERA + 2 * BLOQUE_ADC + 4;
static size_t bytes_iniciar;                  // heap consumido por esp-dsp y los buffers
static float f_interferencia_hz = 2500;
static uint32_t seq_prueba, generadas, diag_enviado, perdidos_previos;
static int64_t t_fuente_us;
static bool fs_hay;
static uint32_t fs_seq0;
static int64_t fs_t0;
static float fs_medida;
static float dc_adc = -1;                     // < 0: se inicia con la media del primer bloque
static uint16_t codigo_min = 4095, codigo_max;  // desde la última consulta "adc"
static uint32_t proc_max_us, proc_total_us, proc_n;
static uint16_t codigos_sint[BLOQUE_ADC];
static uint32_t tramas_enviadas, tramas_descartadas;
static int32_t armado_max_us;
static float bloque_f[BLOQUE_ADC];
static Receptor receptor_uart;
static uint32_t rx_patron_ok, rx_patron_mal;

// IRAM_ATTR y no ARDUINO_ISR_ATTR: en el núcleo 3.x este último no ubica la función en IRAM
// salvo que se active CONFIG_ARDUINO_ISR_IRAM, y desde la flash cada fallo de caché atrasa la
// interrupción y agrega jitter al instante de muestreo.
void IRAM_ATTR al_muestrear() {
  t_alarma_us = (uint32_t)esp_timer_get_time();
  BaseType_t despertar = pdFALSE;
  vTaskNotifyGiveFromISR(tarea_adc_h, &despertar);
  if (despertar) portYIELD_FROM_ISR();
}

// Una lectura por aviso del temporizador. Si la tarea llega tarde, el contador de avisos
// pendientes es > 1: se repite la lectura para conservar la duración del bloque y se cuenta.
void tarea_adc(void*) {
  int activo = 0, idx = 0;
  uint16_t recortadas = 0, atrasadas = 0;
  Jitter j{};
  for (;;) {
    const uint32_t pendientes = ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    const int64_t t0 = esp_timer_get_time();
    const uint32_t retardo = (uint32_t)t0 - t_alarma_us;  // µs desde la última alarma
    if (jitter_reiniciar.exchange(false)) j = Jitter{};
    ++j.n;
    j.suma += retardo;
    j.suma2 += (uint64_t)retardo * retardo;
    j.max_us = std::max(j.max_us, retardo);
    int raw = 0;
    adc_oneshot_read(adc_unidad, CANAL_ADC, &raw);
    const bool pulso = gpio_ll_get_level(&GPIO, PIN_SYNC);  // mismo instante que la muestra
    const int32_t dt = esp_timer_get_time() - t0;
    if (dt > adc_lectura_max_us) adc_lectura_max_us = dt;
    if (pendientes > 1) {
      atrasadas += pendientes - 1;
      adc_atrasadas += pendientes - 1;
    }
    for (uint32_t k = 0; k < pendientes; ++k) {
      if (raw <= 0 || raw >= 4095) {
        ++recortadas;
        ++adc_recortadas;
      }
      const uint8_t bit = 1 << (idx & 7);
      uint8_t& byte = buf_sync[activo][idx >> 3];
      byte = pulso ? byte | bit : byte & ~bit;
      buf_adc[activo][idx++] = raw;
      if (idx < BLOQUE_ADC) continue;
      idx = 0;
      portENTER_CRITICAL(&mux_jitter);
      jitter_publicado = j;
      portEXIT_CRITICAL(&mux_jitter);
      const Bloque b{activo, adc_seq++, adc_perdidos, recortadas, atrasadas, esp_timer_get_time()};
      recortadas = atrasadas = 0;
      const int otro = 1 - activo;
      if (ocupado[otro]) {  // desbordamiento: loop() no liberó el otro búfer; se reescribe este
        ++adc_perdidos;
        continue;
      }
      ocupado[activo] = true;
      xQueueSend(cola_bloques, &b, 0);
      activo = otro;
    }
  }
}

bool iniciar_adc() {
  adc_oneshot_unit_init_cfg_t unidad = {};
  unidad.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&unidad, &adc_unidad) != ESP_OK) return false;
  adc_oneshot_chan_cfg_t canal = {};
  canal.atten = ADC_ATTEN_DB_12;  // atenuación alta: rango útil ~0.15-2.45 V
  canal.bitwidth = ADC_BITWIDTH_12;
  if (adc_oneshot_config_channel(adc_unidad, CANAL_ADC, &canal) != ESP_OK) return false;
  adc_cali_line_fitting_config_t cali = {};
  cali.unit_id = ADC_UNIT_1;
  cali.atten = ADC_ATTEN_DB_12;
  cali.bitwidth = ADC_BITWIDTH_12;
#if CONFIG_IDF_TARGET_ESP32
  cali.default_vref = 1100;  // si el eFuse no trae Vref
#endif
  if (adc_cali_create_scheme_line_fitting(&cali, &adc_cali) != ESP_OK) adc_cali = nullptr;
  cola_bloques = xQueueCreate(2, sizeof(Bloque));
  // Núcleo 0 (sin WiFi) y prioridad máxima; loop() corre en el núcleo 1.
  if (!cola_bloques ||
      xTaskCreatePinnedToCore(tarea_adc, "adc", 4096, nullptr, configMAX_PRIORITIES - 1, &tarea_adc_h, 0) != pdPASS)
    return false;
  hw_timer_t* timer = timerBegin(RELOJ_TIMER_HZ);
  if (!timer || timerGetFrequency(timer) != RELOJ_TIMER_HZ) return false;
  timerAttachInterrupt(timer, &al_muestrear);
  timerAlarm(timer, RELOJ_TIMER_HZ / FS_ADC, true, 0);
  return true;
}

void reiniciar_medicion_fs() {
  fs_hay = false;
  fs_medida = 0;
  dc_adc = -1;
}

// Camino común de todas las fuentes: DC, fs medida, diagnóstico, referencia y trama.
// bits: nivel del pin del pulso por muestra (solo con el ADC; nullptr con las fuentes de prueba).
void procesar_bloque(const uint16_t* codigos, const uint8_t* bits, InfoBloque b, int64_t t_us) {
  if (nodo.binario_pendiente) return;  // una carga de "muestras" usa muestras_tx y el diagnóstico
  const int64_t inicio = esp_timer_get_time();
  // fs = muestras tomadas (por secuencia, incluye bloques perdidos) / tiempo de esp_timer.
  if (!fs_hay) {
    fs_hay = true;
    fs_seq0 = b.seq;
    fs_t0 = t_us;
  } else if (t_us > fs_t0) {
    fs_medida = (float)(b.seq - fs_seq0) * BLOQUE_ADC * 1e6f / (float)(t_us - fs_t0);
  }
  b.fs_medida_hz = fs_medida;
  if (fs_medida > 0 && fabsf(fs_medida - FS_ADC) > TOLERANCIA_FS * FS_ADC) b.estado |= EST_FS_FUERA;
  if (b.recortadas) b.estado |= EST_RECORTE;
  if (b.atrasadas) b.estado |= EST_ATRASO;
  if (b.perdidos != perdidos_previos) {
    b.estado |= EST_PERDIDA;
    // Faltan muestras: la posición en el ciclo se recupera en el próximo pulso.
    sync_perdida(nodo.sync);
    ref_cancelar(nodo.ref, "se perdieron bloques durante la captura");
  }
  perdidos_previos = b.perdidos;
  if (fuente != FUENTE_ADC) b.estado |= EST_PRUEBA;
  b.t_us = (uint32_t)t_us;
  if (fuente == FUENTE_PATRON) {
    for (int i = 0; i < BLOQUE_ADC; ++i) muestras_tx[i] = patron(b.seq, i);
  } else {
    if (dc_adc < 0) {  // primer bloque: arrancar en su media evita un transitorio de segundos
      uint32_t suma = 0;
      for (int i = 0; i < BLOQUE_ADC; ++i) suma += codigos[i];
      dc_adc = (float)suma / BLOQUE_ADC;
    }
    // Pasa altos de primer orden: dc sigue la media lenta y se resta muestra a muestra, así
    // el nivel no salta entre bloques (un salto sonaría como clic en los nodos 2 y 3).
    for (int i = 0; i < BLOQUE_ADC; ++i) {
      dc_adc += ALFA_DC * (codigos[i] - dc_adc);
      muestras_tx[i] = (int16_t)lroundf(codigos[i] - dc_adc);
      bloque_f[i] = muestras_tx[i] / 2048.0f;  // misma entrada que verá Python en la trama
      codigo_min = std::min(codigo_min, codigos[i]);
      codigo_max = std::max(codigo_max, codigos[i]);
    }
    b.dc = (uint16_t)lroundf(dc_adc);
    nodo.muestras_totales = b.seq * BLOQUE_ADC;  // los bloques perdidos no corren el índice
    nodo1_alimentar(nodo, bloque_f, BLOQUE_ADC);
  }
  EventoRef evento = EV_NADA;
  bool con_ref = false;
  if (fuente == FUENTE_ADC) {
    con_ref = sync_bloque(nodo, bits, muestras_tx, BLOQUE_ADC, b, ref_tx, evento);
  } else {
    b.componente = COMP_NINGUNA;
    b.ref_estado = nodo.ref.estado;
  }
  if (evento == EV_LISTA) mostrar_ref(nodo);
  if (evento == EV_CANCELADA) responder(nodo, "ERR ref cancelada: %s\n", nodo.ref.motivo);
  if (nodo.diag.numero != diag_enviado) {
    b.estado |= EST_DIAG_NUEVO;
    diag_enviado = nodo.diag.numero;
  }
  if (tramas_activas) {
    const int64_t t0 = esp_timer_get_time();
    const int largo = armar_trama(trama_tx, b, muestras_tx, BLOQUE_ADC, nodo.diag, nodo.dsp.N, con_ref ? ref_tx : nullptr);
    ultimo_largo = largo;
    armado_max_us = std::max<int32_t>(armado_max_us, esp_timer_get_time() - t0);
    if (Serial2.availableForWrite() < largo) {  // la UART no da abasto: se descarta y el receptor ve el salto
      ++tramas_descartadas;
    } else {
      Serial2.write(trama_tx, largo);
      ++tramas_enviadas;
      if (ver_tramas) describir_trama(nodo, trama_tx, false);
    }
    // Copia por USB para capturar sin adaptador. El texto de la consola queda entre tramas y el
    // receptor lo descarta: busca el delimitador y valida el CRC.
    if (tramas_usb) {
      if (Serial.availableForWrite() < largo) {
        ++tramas_usb_descartadas;
      } else {
        Serial.write(trama_tx, largo);
        ++tramas_usb_enviadas;
      }
    }
  }
  const uint32_t dt = esp_timer_get_time() - inicio;
  proc_max_us = std::max(proc_max_us, dt);
  proc_total_us += dt;
  ++proc_n;
}

void consumir_adc() {
  Bloque bq;
  while (xQueueReceive(cola_bloques, &bq, 0) == pdTRUE) {
    if (fuente == FUENTE_ADC)
      procesar_bloque(buf_adc[bq.idx], buf_sync[bq.idx], InfoBloque{bq.seq, 0, bq.recortadas, bq.atrasadas, bq.perdidos, 0, 0, 0},
                      bq.t_us);
    ocupado[bq.idx] = false;  // libera el búfer para la tarea del ADC
  }
}

// Fuentes de prueba sin hardware de entrada, al ritmo de fs, por bloques completos.
void avanzar_fuente_prueba() {
  const uint64_t debidas = (uint64_t)(esp_timer_get_time() - t_fuente_us) * FS_ADC / 1000000;
  while (generadas + BLOQUE_ADC <= debidas) {
    for (int i = 0; i < BLOQUE_ADC && fuente == FUENTE_SINT; ++i) {  // el patrón se arma en procesar_bloque
      const float t = (float)((generadas + i) % FS_ADC) / FS_ADC;  // fase exacta cada segundo si f es entera
      const float x = sinf(2 * PI * 440 * t) + 0.55f * sinf(2 * PI * 880 * t + 0.61f) +
                      0.3f * sinf(2 * PI * 1320 * t - 0.87f) + 0.8f * sinf(2 * PI * f_interferencia_hz * t);
      codigos_sint[i] = (uint16_t)std::min(4095L, std::max(0L, lroundf(2048 + 700 * x)));
    }
    generadas += BLOQUE_ADC;
    procesar_bloque(codigos_sint, nullptr, InfoBloque{seq_prueba++, 0, 0, 0, 0, 0, 0, 0},
                    t_fuente_us + (int64_t)generadas * 1000000 / FS_ADC);
  }
}

// Tramas que vuelven por UART2 RX (puente GPIO17 -> GPIO16 o eco de otro nodo).
void leer_uart_rx() {
  while (Serial2.available() > 0)
    if (receptor_byte(receptor_uart, Serial2.read())) (trama_es_patron(receptor_uart.buf) ? rx_patron_ok : rx_patron_mal)++;
}

void escribir_serial(const char* texto) { Serial.print(texto); }

int memoria_esp(char* buf, int cap) {
  return snprintf(buf, cap,
                  ",\"bytes_iniciar\":%u,\"heap_interno_libre\":%u,\"heap_interno_minimo\":%u,"
                  "\"bloque_mayor\":%u,\"pila_libre_loop\":%u,\"pila_libre_adc\":%u",
                  (unsigned)bytes_iniciar, (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                  (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                  (unsigned)uxTaskGetStackHighWaterMark(NULL),  // en ESP-IDF, bytes
                  (unsigned)uxTaskGetStackHighWaterMark(tarea_adc_h));
}

int milivoltios(int codigo) {
  int mv = -1;
  if (adc_cali) adc_cali_raw_to_voltage(adc_cali, codigo, &mv);
  return mv;
}

// Estado de la captura. El mín./máx. se reinicia en cada consulta: sirve para ajustar la
// ganancia del micrófono mirando solo el último intervalo.
void mostrar_adc() {
  static const char* const NOMBRES[] = {"adc", "sint", "patron", "nada"};
  const int largo = ultimo_largo;  // con referencia la trama mide el doble
  const float bytes_s = largo * (float)FS_ADC / BLOQUE_ADC;
  const float envio_ms = 1000.0f * largo * 10 / BAUDIOS_TRAMA;
  const int dc = dc_adc < 0 ? 0 : (int)lroundf(dc_adc);
  portENTER_CRITICAL(&mux_jitter);
  const Jitter j = jitter_publicado;
  portEXIT_CRITICAL(&mux_jitter);
  const double media_j = j.n ? (double)j.suma / j.n : 0;
  const double desv_j = j.n ? sqrt(std::max(0.0, (double)j.suma2 / j.n - media_j * media_j)) : 0;
  Serial.printf("ADC {\"fuente\":\"%s\",\"fs_nominal_hz\":%lu,\"fs_medida_hz\":%.3f,\"bloques\":%lu,"
                "\"bloques_perdidos\":%lu,\"muestras_atrasadas\":%lu,\"muestras_recortadas\":%lu,"
                "\"lectura_max_us\":%ld,\"dc_codigo\":%lu,\"dc_mv\":%d,\"codigo_min\":%u,\"codigo_max\":%u,"
                "\"min_mv\":%d,\"max_mv\":%d,\"calibrado\":%s,\"proceso_medio_us\":%lu,\"proceso_max_us\":%lu,"
                "\"latencia_bloque_ms\":%.1f,\"tramas_enviadas\":%lu,\"tramas_descartadas\":%lu,"
                "\"armado_max_us\":%ld,\"baudios\":%lu,\"uso_uart_pct\":%.1f,"
                "\"retardo_lectura_medio_us\":%.2f,\"jitter_muestreo_us\":%.2f,\"retardo_lectura_max_us\":%lu,"
                "\"bytes_por_trama\":%d,\"tramas_usb\":%s,\"tramas_usb_enviadas\":%lu,\"tramas_usb_descartadas\":%lu}\n",
                NOMBRES[fuente], (unsigned long)FS_ADC, fs_medida, (unsigned long)adc_seq.load(),
                (unsigned long)adc_perdidos.load(), (unsigned long)adc_atrasadas.load(),
                (unsigned long)adc_recortadas.load(), (long)adc_lectura_max_us.load(), (unsigned long)dc,
                milivoltios(dc), codigo_min, codigo_max, milivoltios(codigo_min), milivoltios(codigo_max),
                adc_cali ? "true" : "false", (unsigned long)(proc_n ? proc_total_us / proc_n : 0),
                (unsigned long)proc_max_us,
                // llenado del bloque + peor procesamiento + salida completa de la trama por la UART
                1000.0f * BLOQUE_ADC / FS_ADC + proc_max_us / 1000.0f + envio_ms, (unsigned long)tramas_enviadas,
                (unsigned long)tramas_descartadas, (long)armado_max_us, (unsigned long)BAUDIOS_TRAMA,
                100 * bytes_s * 10 / BAUDIOS_TRAMA, media_j, desv_j, (unsigned long)j.max_us, largo,
                tramas_usb ? "true" : "false", (unsigned long)tramas_usb_enviadas, (unsigned long)tramas_usb_descartadas);
  jitter_reiniciar = true;  // como el mín./máx.: cada consulta mide el intervalo desde la anterior
  codigo_min = 4095;
  codigo_max = 0;
}

bool comando_esp(const char* cmd, const char* arg) {
  if (!strcmp(cmd, "fuente") && arg) {
    const char* const NOMBRES[] = {"adc", "sint", "patron", "nada"};
    int i = 0;
    while (i < 4 && strcmp(arg, NOMBRES[i])) ++i;
    if (i == 4) return false;
    fuente = (Fuente)i;
    generadas = seq_prueba = 0;
    t_fuente_us = esp_timer_get_time();
    reiniciar_medicion_fs();
    dsp_reiniciar(nodo.dsp);
    Serial.printf("OK fuente %s\n", arg);
  } else if (!strcmp(cmd, "interferencia") && arg) {  // cambia el ruido en vivo para ver la readaptación
    f_interferencia_hz = atof(arg);
    Serial.printf("OK interferencia %.1f Hz\n", f_interferencia_hz);
  } else if (!strcmp(cmd, "adc")) {
    mostrar_adc();
  } else if (!strcmp(cmd, "ver") && arg) {
    ver_tramas = !strcmp(arg, "on");
    Serial.printf("OK ver %s\n", ver_tramas ? "on" : "off");
  } else if (!strcmp(cmd, "tramas") && arg) {
    tramas_activas = !strcmp(arg, "on");
    Serial.printf("OK tramas %s\n", tramas_activas ? "on" : "off");
  } else if (!strcmp(cmd, "tramas_usb") && arg) {
    // Se responde antes de activar: el OK no queda detrás de tramas binarias.
    Serial.printf("OK tramas_usb %s\n", !strcmp(arg, "on") ? "on" : "off");
    Serial.flush();
    tramas_usb = !strcmp(arg, "on");
    tramas_usb_enviadas = tramas_usb_descartadas = 0;
  } else if (!strcmp(cmd, "rx")) {
    if (arg && !strcmp(arg, "reiniciar")) receptor_reiniciar(receptor_uart), rx_patron_ok = rx_patron_mal = 0;
    Serial.printf("RX {\"validas\":%lu,\"errores_crc\":%lu,\"perdidas\":%lu,\"bytes_descartados\":%lu,"
                  "\"patron_ok\":%lu,\"patron_mal\":%lu}\n",
                  (unsigned long)receptor_uart.ok, (unsigned long)receptor_uart.errores_crc,
                  (unsigned long)receptor_uart.perdidas, (unsigned long)receptor_uart.descartados,
                  (unsigned long)rx_patron_ok, (unsigned long)rx_patron_mal);
  } else {
    return false;
  }
  return true;
}

void setup() {
  Serial.setRxBufferSize(8192);  // la carga binaria de "muestras" llega en ráfagas
  Serial.setTxBufferSize(16384); // un DIAG (hasta ~6 KB) y, con tramas_usb, dos tramas con referencia
  Serial.begin(921600);          // consola por el puente USB-UART (CP2102/CH340)
  Serial2.setTxBufferSize(8192); // una trama con referencia (4192 B) sin bloquear loop()
  Serial2.setRxBufferSize(8192);
  Serial2.begin(BAUDIOS_TRAMA, SERIAL_8N1, PIN_TRAMA_RX, PIN_TRAMA_TX);
  // GPIO35 no tiene pull interno: sin el cable del emisor conviene 100 kΩ a GND para que no flote.
  pinMode(PIN_SYNC, INPUT);
  delay(1000);
  nodo.escribir = escribir_serial;
  nodo.memoria_plataforma = memoria_esp;
  nodo.comando_plataforma = comando_esp;
  nodo.bloque_real = bloque_f;
  receptor_reiniciar(receptor_uart);
  const size_t antes = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  if (!nodo1_iniciar(nodo)) {
    Serial.println("ERR no se pudo iniciar esp-dsp o reservar buffers");
    while (true) delay(1000);
  }
  bytes_iniciar = antes - heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  if (!iniciar_adc()) {
    Serial.println("ERR no se pudo iniciar el ADC, la tarea o el temporizador");
    while (true) delay(1000);
  }
  Serial.println("OK nodo 1 listo: micrófono en GPIO34 a 16 kHz, pulso del emisor en GPIO35, tramas por GPIO17; '?' muestra comandos");
}

void loop() {
  static uint8_t buf[512];
  const int disponibles = Serial.available();
  if (disponibles > 0) nodo1_bytes(nodo, buf, Serial.readBytes(buf, std::min(disponibles, (int)sizeof(buf))));
  consumir_adc();
  if (fuente == FUENTE_SINT || fuente == FUENTE_PATRON) avanzar_fuente_prueba();
  leer_uart_rx();
}

// ============================================================================
// PC: consola por stdin/stdout para validar sin placa (nodo1/host/Makefile)
// ============================================================================
#else

void escribir_stdout(const char* texto) {
  fputs(texto, stdout);
  fflush(stdout);
}

int main() {
  nodo.escribir = escribir_stdout;
  if (!nodo1_iniciar(nodo)) return 1;
  uint8_t buf[4096];
  ssize_t n;
  while ((n = read(0, buf, sizeof(buf))) > 0) nodo1_bytes(nodo, buf, n);
  return 0;
}

#endif
