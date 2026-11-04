/* Prueba básica del micrófono MAX4466 en el nodo 1 (sin el firmware completo).
 * Conexión: VCC -> filtro -> 3V3, GND -> GND, OUT -> R1 -> R2 -> GPIO4 (igual que el nodo 1).
 * GPIO4 es ADC2: funciona porque aquí no se usa el WiFi.
 * Monitor serie a 115200 baudios. Cada medio segundo imprime:
 *   DC   : nivel medio en mV. Micrófono sano y bien conectado: ≈ 1650 mV.
 *   p-p  : variación pico a pico en mV. Sube al aplaudir o hablar cerca.
 * Si DC queda cerca de 0 o de 3000+ mV, o p-p no cambia con el sonido, revisar el cableado
 * o el micrófono. Después, volver a cargar nodo1_esp32.ino.
 */
#include <Arduino.h>

constexpr int PIN_MIC = 4;
constexpr int MUESTRAS = 2000;  // ≈ 0.25 s

void setup() {
  Serial.begin(115200);
  analogSetPinAttenuation(PIN_MIC, ADC_11db);  // rango ≈ 0.15–2.45 V lineal, como el nodo 1
  delay(500);
  Serial.println("Prueba del microfono: DC deberia ser ~1650 mV; aplauda y mire p-p.");
}

void loop() {
  long suma = 0;
  int minimo = 5000, maximo = 0;
  for (int i = 0; i < MUESTRAS; ++i) {
    const int mv = analogReadMilliVolts(PIN_MIC);
    suma += mv;
    minimo = min(minimo, mv);
    maximo = max(maximo, mv);
    delayMicroseconds(100);
  }
  const int dc = suma / MUESTRAS;
  const char* estado = dc < 300 ? "MUY BAJO: OUT suelto o sin VCC?"
                     : dc > 2600 ? "MUY ALTO: falta GND, VCC y OUT cruzados, o micro danado?"
                     : (dc > 1400 && dc < 1900) ? "OK"
                     : "raro, revisar";
  Serial.printf("DC %4d mV | min %4d  max %4d | p-p %4d mV | %s\n", dc, minimo, maximo, maximo - minimo, estado);
  delay(250);
}
