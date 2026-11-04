/* Emisor del banco de pruebas. ESP32-WROOM-32, Arduino-ESP32 3.3.2 (ESP-IDF 5.5).
 * Salida por el DAC de 8 bits de GPIO25 a 16 kHz. Las señales se generan en vivo
 * (generador.h); solo la canción de P3 viene guardada en flash (audio.h).
 * Una tarea calcula las muestras y llena un búfer circular en RAM; la interrupción del
 * temporizador solo saca una muestra por periodo al DAC, sin cálculos ni accesos a flash.
 * Comandos por monitor serial a 115200 baudios; "?" muestra la ayuda.
 */
#include <Arduino.h>
#include <driver/dac_oneshot.h>
#include <hal/dac_ll.h>
#include <hal/gpio_ll.h>
#include "generador.h"
#if !CONFIG_IDF_TARGET_ESP32
#error "Este firmware requiere el ESP32 clasico (WROOM-32): usa el DAC de GPIO25."
#endif

constexpr uint32_t RELOJ_TEMPORIZADOR = 2000000;  // 80 MHz / 40
static_assert(RELOJ_TEMPORIZADOR % FS_HZ == 0, "fs debe dividir exactamente el reloj del temporizador");
// Pulso al inicio de cada ciclo de la señal útil. Su ancho dice qué componente se emite:
// 1 ms mezcla, 2 ms limpia, 3 ms ruido. En silencio no hay pulsos. Lo lee el nodo 1.
constexpr int PIN_SYNC = 27;
constexpr uint32_t MUESTRAS_MS = FS_HZ / 1000;
constexpr uint32_t TAM_BUFER = 4096;         // 256 ms; potencia de dos para el índice circular.
constexpr uint32_t BLOQUE = 256;             // Muestras que calcula la tarea en cada vuelta.

static DRAM_ATTR uint8_t bufer[TAM_BUFER];
static volatile uint32_t lectura = 0, escritura = 0;   // contadores libres; índice = contador % TAM_BUFER
static volatile uint32_t vaciados = 0, saturadas = 0, posicion = 0, periodoSync = 0, muestrasSync = 0;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static Fuente fuenteNueva;                   // la escribe loop() y la toma la tarea, siempre bajo mux
static volatile bool hayNueva = false;
static Config cfg;
static Fuente activa;                         // copia de lo que suena, solo para "estado"
static hw_timer_t* temporizador = nullptr;
static dac_oneshot_handle_t dac = nullptr;
static uint32_t lecturaPrevia = 0, microsPrevios = 0;

// IRAM_ATTR y no ARDUINO_ISR_ATTR: en el núcleo 3.x este último no ubica la función en IRAM
// salvo que se active CONFIG_ARDUINO_ISR_IRAM, y desde flash cada fallo de caché agrega jitter.
void IRAM_ATTR alMuestrear() {
  portENTER_CRITICAL_ISR(&mux);
  if (lectura != escritura) {
    dac_ll_update_output_value(DAC_CHAN_0, bufer[lectura % TAM_BUFER]);
    lectura = lectura + 1;
    gpio_ll_set_level(&GPIO, (gpio_num_t)PIN_SYNC, periodoSync && posicion < muestrasSync);
    if (periodoSync) {
      const uint32_t p = posicion + 1;
      posicion = p >= periodoSync ? 0 : p;
    }
  } else {
    vaciados = vaciados + 1;                   // la tarea no alcanzó a llenar el búfer
  }
  portEXIT_CRITICAL_ISR(&mux);
}

uint32_t anchoSyncMs(Componente c) { return c == Componente::Limpia ? 2 : c == Componente::Ruido ? 3 : 1; }

uint8_t codigoDac(float x) {
  if (x > 1 || x < -1) {
    x = x > 1 ? 1 : -1;
    saturadas = saturadas + 1;
  }
  return (uint8_t)lrintf(127.5f + 127.5f * x);  // -1 -> 0, 0 -> 128, 1 -> 255
}

void tareaProductora(void*) {
  Fuente local;
  local.iniciar(Config{});
  for (;;) {
    if (hayNueva) {
      // Cambio de modo: se descarta lo pendiente para que la señal nueva empiece en el índice 0.
      // El primer bloque se calcula antes de vaciar el búfer, para que la interrupción no lo
      // encuentre vacío mientras tanto.
      static uint8_t primero[BLOQUE];
      portENTER_CRITICAL(&mux);
      local = fuenteNueva;
      hayNueva = false;
      portEXIT_CRITICAL(&mux);
      for (uint32_t i = 0; i < BLOQUE; ++i)
        primero[i] = local.cfg.activo ? codigoDac(local.ganancia * local.valor()) : 128;
      portENTER_CRITICAL(&mux);
      for (uint32_t i = 0; i < BLOQUE; ++i) bufer[(lectura + i) % TAM_BUFER] = primero[i];
      escritura = lectura + BLOQUE;
      posicion = 0;
      periodoSync = local.cfg.activo ? local.periodo : 0;
      muestrasSync = MUESTRAS_MS * anchoSyncMs(local.cfg.componente);
      vaciados = 0;
      portEXIT_CRITICAL(&mux);
      continue;
    }
    if (TAM_BUFER - (escritura - lectura) < BLOQUE) {
      vTaskDelay(1);
      continue;
    }
    const uint32_t inicio = escritura;
    for (uint32_t i = 0; i < BLOQUE; ++i)
      bufer[(inicio + i) % TAM_BUFER] = local.cfg.activo ? codigoDac(local.ganancia * local.valor()) : 128;
    escritura = inicio + BLOQUE;               // se publica después de escribir las muestras
  }
}

void aplicar() {
  Fuente f;
  calibrar(cfg, f);
  portENTER_CRITICAL(&mux);
  fuenteNueva = f;
  hayNueva = true;
  saturadas = 0;
  portEXIT_CRITICAL(&mux);
  activa = f;
}

const char* nombreComponente(Componente c) {
  return c == Componente::Limpia ? "limpia" : c == Componente::Ruido ? "ruido" : "mezcla";
}

void mostrarAyuda() {
  Serial.println(F("\nComandos (terminar con Enter):"));
  Serial.println(F("  p <1..5>                carga la prueba P1..P5 y emite"));
  Serial.println(F("  s                       emite con los parametros actuales"));
  Serial.println(F("  0                       silencio (DAC en 128)"));
  Serial.println(F("  tonos f[:a] ...         senal util: hasta 4 tonos (ej.: tonos 440:1 880:0.55)"));
  Serial.println(F("  audio                   senal util: la cancion guardada (P3)"));
  Serial.println(F("  chirp <f0> <f1> <ms> <periodo_s>  senal util: rafaga de barrido repetida"));
  Serial.println(F("  ruido ninguno | tono <f> | blanco | banda <f1> <f2> | impulsivo <por_s>"));
  Serial.println(F("  snr <dB>                SNR de la mezcla (-40 a 60)"));
  Serial.println(F("  comp mezcla|limpia|ruido  componente que se emite"));
  Serial.println(F("  vol <0..1>              volumen relativo al pico de 0.8"));
  Serial.println(F("  semilla <n>             semilla del ruido"));
  Serial.println(F("  estado                  parametros, fs medida, saturaciones y vaciados"));
  Serial.println(F("Pruebas: P1 tono 440 + tono 2508 | P2 3 tonos + banda 2500-3800 | P3 audio + banda 2000-7500"));
  Serial.println(F("         P4 chirp 600-1400 Hz 50 ms/1 s + impulsivo 4/s | P5 3 tonos + banda 1000-1800. Todas a 2 dB."));
}

void mostrarEstado() {
  const uint32_t ahora = micros(), leidas = lectura;
  const float fsMedida = (leidas - lecturaPrevia) * 1e6f / (uint32_t)(ahora - microsPrevios);
  lecturaPrevia = leidas;
  microsPrevios = ahora;
  Serial.printf("%s | componente %s | SNR %.2f dB | volumen %.2f | ganancia %.4f\n", cfg.activo ? "Emitiendo" : "Silencio",
                nombreComponente(cfg.componente), cfg.snr_db, cfg.volumen, activa.ganancia);
  if (cfg.util == TipoUtil::Audio) Serial.print("Util: audio");
  else if (cfg.util == TipoUtil::Chirp)
    Serial.printf("Util: chirp %.1f-%.1f Hz, %.1f ms cada %.3f s", cfg.chirp_f[0], cfg.chirp_f[1], cfg.rafaga_ms, cfg.periodo_rafaga_s);
  else {
    Serial.print("Util: tonos");
    for (uint32_t i = 0; i < cfg.ntonos; ++i) Serial.printf(" %.1f:%.3f", cfg.frec[i], cfg.amp[i]);
  }
  switch (cfg.ruido) {
    case TipoRuido::Ninguno: Serial.print(" | ruido ninguno"); break;
    case TipoRuido::Tono: Serial.printf(" | ruido tono %.1f Hz", cfg.frec_ruido); break;
    case TipoRuido::Blanco: Serial.print(" | ruido blanco"); break;
    case TipoRuido::Banda: Serial.printf(" | ruido banda %.1f-%.1f Hz", cfg.banda[0], cfg.banda[1]); break;
    case TipoRuido::Impulsivo: Serial.printf(" | ruido impulsivo %.2f/s", cfg.tasa); break;
  }
  Serial.printf(" | semilla %lu\n", (unsigned long)cfg.semilla);
  if (cfg.activo) Serial.printf("Sincronizacion GPIO%d: pulso de %lu ms cada %.3f s\n", PIN_SYNC,
                                (unsigned long)anchoSyncMs(cfg.componente), activa.periodo / (float)FS_HZ);
  Serial.printf("fs nominal %lu Hz, medida %.1f Hz | saturadas %lu | vaciados %lu\n",
                (unsigned long)FS_HZ, fsMedida, (unsigned long)saturadas, (unsigned long)vaciados);
}

bool frecuenciaValida(float f) { return f > 0 && f < FS_HZ / 2.0f; }

// Interpreta una línea sobre una copia de cfg; solo se aplica si todo es válido.
bool procesar(char* linea) {
  char* palabra = strtok(linea, " \t");
  if (!palabra) return false;
  Config c = cfg;
  auto siguiente = []() { return strtok(nullptr, " \t"); };
  auto numero = [&](float& v) { char* t = siguiente(); char* fin; if (!t) return false; v = strtof(t, &fin); return *fin == 0 && isfinite(v); };
  String cmd(palabra);
  if (cmd == "?") { mostrarAyuda(); return false; }
  if (cmd == "estado") { mostrarEstado(); return false; }
  if (cmd == "0") {
    c.activo = false;
  } else if (cmd == "s") {
    c.activo = true;
  } else if (cmd == "p") {
    float v;
    if (!numero(v) || !cargarPrueba((int)v, c)) { Serial.println("Use: p <1..5>"); return false; }
  } else if (cmd == "audio") {
    c.util = TipoUtil::Audio;
  } else if (cmd == "chirp") {
    if (!numero(c.chirp_f[0]) || !numero(c.chirp_f[1]) || !numero(c.rafaga_ms) || !numero(c.periodo_rafaga_s) ||
        !frecuenciaValida(c.chirp_f[0]) || !frecuenciaValida(c.chirp_f[1]) || c.rafaga_ms < 1 ||
        c.periodo_rafaga_s > 10 || c.rafaga_ms >= 1000 * c.periodo_rafaga_s) {
      Serial.println("Use: chirp <f0> <f1> <ms> <periodo_s>, con 0 < f < 8000, 1 <= ms < periodo y periodo <= 10 s");
      return false;
    }
    c.util = TipoUtil::Chirp;
  } else if (cmd == "comp") {
    String t = siguiente();
    if (t == "mezcla") c.componente = Componente::Mezcla;
    else if (t == "limpia") c.componente = Componente::Limpia;
    else if (t == "ruido") c.componente = Componente::Ruido;
    else { Serial.println("Use: comp mezcla|limpia|ruido"); return false; }
  } else if (cmd == "snr") {
    float v;
    if (!numero(v) || v < -40 || v > 60) { Serial.println("Use: snr <dB entre -40 y 60>"); return false; }
    c.snr_db = v;
  } else if (cmd == "vol") {
    if (!numero(c.volumen) || c.volumen < 0 || c.volumen > 1) { Serial.println("Use: vol <0..1>"); return false; }
  } else if (cmd == "tonos") {
    uint32_t n = 0;
    for (char* t = siguiente(); t; t = siguiente()) {
      if (n == MAX_TONOS) { Serial.println("Maximo 4 tonos."); return false; }
      char* fin;
      c.frec[n] = strtof(t, &fin);
      c.amp[n] = *fin == ':' ? strtof(fin + 1, &fin) : 1.0f;
      if (*fin != 0 || !frecuenciaValida(c.frec[n]) || !(c.amp[n] > 0)) {
        Serial.println("Use: tonos f[:a] ... con 0 < f < 8000 y a > 0"); return false;
      }
      ++n;
    }
    if (!n) { Serial.println("Indique al menos un tono."); return false; }
    c.ntonos = n;
    c.util = TipoUtil::Tonos;
  } else if (cmd == "ruido") {
    String t = siguiente();
    if (t == "ninguno") c.ruido = TipoRuido::Ninguno;
    else if (t == "blanco") c.ruido = TipoRuido::Blanco;
    else if (t == "tono" && numero(c.frec_ruido) && frecuenciaValida(c.frec_ruido)) c.ruido = TipoRuido::Tono;
    else if (t == "banda" && numero(c.banda[0]) && numero(c.banda[1]) && frecuenciaValida(c.banda[0]) &&
             frecuenciaValida(c.banda[1]) && c.banda[0] < c.banda[1]) c.ruido = TipoRuido::Banda;
    else if (t == "impulsivo" && numero(c.tasa) && c.tasa > 0 && c.tasa <= FS_HZ) c.ruido = TipoRuido::Impulsivo;
    else { Serial.println("Use: ruido ninguno | tono <f> | blanco | banda <f1> <f2> | impulsivo <por_s>"); return false; }
  } else if (cmd == "semilla") {
    float v;
    if (!numero(v) || v < 1 || v > 4294967295.0f) { Serial.println("Use: semilla <entero positivo>"); return false; }
    c.semilla = (uint32_t)v;
  } else {
    Serial.println("Comando desconocido; '?' muestra la ayuda.");
    return false;
  }
  cfg = c;
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(PIN_SYNC, OUTPUT);
  digitalWrite(PIN_SYNC, LOW);
  const dac_oneshot_config_t dc = {.chan_id = DAC_CHAN_0};  // DAC_CHAN_0 = GPIO25
  ESP_ERROR_CHECK(dac_oneshot_new_channel(&dc, &dac));
  ESP_ERROR_CHECK(dac_oneshot_output_voltage(dac, 128));    // reposo: ~1.65 V
  xTaskCreatePinnedToCore(tareaProductora, "productora", 4096, nullptr, 2, nullptr, 0);
  // 2 MHz / 125 = 16000 muestras/s exactas en cuentas del reloj.
  temporizador = timerBegin(RELOJ_TEMPORIZADOR);
  if (!temporizador || timerGetFrequency(temporizador) != RELOJ_TEMPORIZADOR) {
    Serial.println("ERROR: no se pudo configurar el temporizador de 2 MHz.");
    while (true) delay(1000);
  }
  timerAttachInterrupt(temporizador, &alMuestrear);
  timerAlarm(temporizador, RELOJ_TEMPORIZADOR / FS_HZ, true, 0);
  microsPrevios = micros();
  Serial.printf("Emisor listo: DAC GPIO25, pulso de sincronizacion GPIO%d, fs=%lu Hz. Inicia en silencio.\n",
                PIN_SYNC, (unsigned long)FS_HZ);
  mostrarAyuda();
}

void loop() {
  static char linea[96];
  static size_t largo = 0;
  while (Serial.available()) {
    const char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (!largo) continue;
      linea[largo] = 0;
      largo = 0;
      if (procesar(linea)) {
        aplicar();
        // Espera a que la tarea tome la señal nueva (reinicia los contadores) antes de informar.
        for (const uint32_t t = millis(); hayNueva && millis() - t < 100;) delay(1);
        mostrarEstado();
      }
    } else if (largo < sizeof(linea) - 1) {
      linea[largo++] = ch;
    }
  }
  delay(1);                                    // solo consola; no marca el ritmo de las muestras
}
