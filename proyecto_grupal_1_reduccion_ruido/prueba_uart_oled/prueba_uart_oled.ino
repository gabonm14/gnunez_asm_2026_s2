/* Prueba de recepción de las tramas del nodo 1 en el ESP32-S3 del nodo 2.
 * Conexión: GPIO17 (TX) del nodo 1 -> GPIO16 (RX) de este S3, y GND común.
 * Cada 0.5 s imprime los bytes recibidos y, sobre todo, las tramas válidas (delimitador A5 5A,
 * versión 3 y CRC-32 correctos), los errores de CRC, las tramas perdidas (saltos en la
 * secuencia) y el contenido de la última trama: secuencia, estado, diagnóstico y primeras muestras.
 * Esperado con el nodo 1 capturando: ≈ 7.8 tramas por 0.5 s (una cada 64 ms), 0 errores de CRC
 * y 0 perdidas. Si llegan bytes pero 0 tramas válidas, el baud rate o el cable están mal.
 * El formato es el de nodo1/validacion/trama.py.
 */
#include <Arduino.h>

// Consola en el UART0: el mismo puerto donde salen los mensajes de arranque del S3. Con
// "USB CDC On Boot" activado, Serial iría al USB nativo y en este monitor no se vería nada.
#if ARDUINO_USB_CDC_ON_BOOT
#define CONSOLA Serial0
#else
#define CONSOLA Serial
#endif

constexpr int PIN_RX = 16, PIN_TX = 15;
constexpr uint32_t BAUDIOS = 921600;       // igual que BAUDIOS_TRAMA del nodo 1
constexpr int CABECERA = 92, N_MAX = 2048;
constexpr uint8_t SYNC0 = 0xA5, SYNC1 = 0x5A, VERSION = 3;
constexpr uint16_t EST_REF = 64;           // bit del estado: la trama trae la referencia limpia
const char* const TIPOS[] = {"impulsivo", "red_electrica", "tonal", "banda"};

static uint8_t buf[CABECERA + 4 * N_MAX + 4];
static int n = 0, esperado = 0;
static uint32_t tabla_crc[256];
static uint32_t validas = 0, errores_crc = 0, perdidas = 0, ultima_seq = 0;
static bool hay_seq = false, hay_trama = false;

uint16_t leer16(const uint8_t* p) { return p[0] | p[1] << 8; }
uint32_t leer32(const uint8_t* p) { return leer16(p) | (uint32_t)leer16(p + 2) << 16; }
float leerf(const uint8_t* p) { uint32_t u = leer32(p); float v; memcpy(&v, &u, 4); return v; }

// CRC-32 IEEE (el mismo del nodo 1 y de zlib.crc32).
uint32_t crc32(const uint8_t* p, size_t len) {
  if (!tabla_crc[1])
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      tabla_crc[i] = c;
    }
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; ++i) c = tabla_crc[(c ^ p[i]) & 0xFF] ^ (c >> 8);
  return ~c;
}

// Igual que receptor_byte del nodo 1: devuelve true cuando buf tiene una trama completa y válida.
bool recibir(uint8_t b) {
  if (n == 1 && b != SYNC1) n = 0;
  if (n == 0) {
    if (b == SYNC0) buf[n++] = b;
    return false;
  }
  buf[n++] = b;
  if (n == 4 && (buf[2] != VERSION || buf[3] != CABECERA)) { n = 0; return false; }
  if (n == 10 && (leer16(buf + 8) == 0 || leer16(buf + 8) > N_MAX)) { n = 0; return false; }
  if (n == 12) esperado = CABECERA + 2 * leer16(buf + 8) * (leer16(buf + 10) & EST_REF ? 2 : 1) + 4;
  if (n < 12 || n < esperado) return false;
  n = 0;
  if (crc32(buf + 2, esperado - 6) != leer32(buf + esperado - 4)) { ++errores_crc; return false; }
  const uint32_t seq = leer32(buf + 4);
  if (hay_seq && seq != ultima_seq + 1) perdidas += seq - ultima_seq - 1;
  ultima_seq = seq;
  hay_seq = true;
  ++validas;
  return true;
}

void setup() {
  CONSOLA.begin(115200);                     // monitor serie del S3 (solo consola; el enlace va por Serial1)
  Serial1.setRxBufferSize(16384);            // el de fábrica (256 B) se llena en < 3 ms a 921600
  Serial1.begin(BAUDIOS, SERIAL_8N1, PIN_RX, PIN_TX);
  delay(500);
  CONSOLA.println("Esperando tramas del nodo 1 (GPIO17 -> GPIO16, GND comun)...");
}

void loop() {
  static uint32_t bytes = 0, inicio = 0, validas_antes = 0;
  static uint8_t ultima[CABECERA + 2 * 8];   // cabecera y primeras 8 muestras de la última trama
  while (Serial1.available() > 0) {
    ++bytes;
    if (recibir(Serial1.read())) {
      memcpy(ultima, buf, sizeof(ultima));
      hay_trama = true;
    }
  }
  if (millis() - inicio < 500) return;
  inicio = millis();
  CONSOLA.printf("bytes %lu | tramas validas %lu (total %lu) | CRC malo %lu | perdidas %lu\n", (unsigned long)bytes,
                (unsigned long)(validas - validas_antes), (unsigned long)validas, (unsigned long)errores_crc,
                (unsigned long)perdidas);
  if (hay_trama) {
    const uint16_t estado = leer16(ultima + 10);
    CONSOLA.printf("   seq %lu | estado 0x%02x%s | diagnostico #%lu tipos [", (unsigned long)leer32(ultima + 4), estado,
                  estado & EST_REF ? " (con referencia)" : "", (unsigned long)leer32(ultima + 24));
    for (int i = 0, primero = 1; i < 4; ++i)
      if (ultima[28] & (1 << i)) CONSOLA.printf(primero ? "%s" : ",%s", TIPOS[i]), primero = 0;
    CONSOLA.printf("] lineas [");
    for (int i = 0; i < ultima[30]; ++i) CONSOLA.printf(i ? ", %.1f" : "%.1f", leerf(ultima + 36 + 4 * i));
    CONSOLA.printf("] Hz | banda %.0f-%.0f Hz | muestras:", leerf(ultima + 52), leerf(ultima + 56));
    for (int i = 0; i < 8; ++i) CONSOLA.printf(" %d", (int16_t)leer16(ultima + CABECERA + 2 * i));
    CONSOLA.println();
  }
  bytes = 0;
  validas_antes = validas;
}
