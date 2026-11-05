/* Prueba mínima de la UART del nodo 1 (el que envía). Se carga en el NODO 1.
 * Cada medio segundo manda por GPIO17 (UART2 TX) un texto "HOLA <n>" y lo muestra también
 * en el monitor serie de este ESP32 (115200), para saber qué se envió.
 *
 * Conexión:  nodo 1 GPIO17 (TX) ──► GPIO16 (RX) del otro ESP32 (nodos 2/3)
 *            nodo 1 GND ────────── GND del otro ESP32
 * En el otro ESP32: prueba_uart_eco.ino. Si allá aparecen los mismos "HOLA <n>", el cable funciona.
 * Prueba sin el otro ESP32: puente GPIO17 → GPIO16 en este mismo nodo; debe aparecer "Recibido: HOLA <n>".
 * Después, volver a cargar nodo1_esp32.ino.
 */
#include <Arduino.h>

constexpr int PIN_RX = 16, PIN_TX = 17;
constexpr uint32_t BAUDIOS = 115200;  // lento a propósito: si esto funciona, el cable está bien

void setup() {
  Serial.begin(115200);
  Serial2.begin(BAUDIOS, SERIAL_8N1, PIN_RX, PIN_TX);
  delay(300);
  Serial.println("Nodo 1: enviando HOLA <n> por GPIO17 cada 0.5 s");
}

void loop() {
  static uint32_t n = 0, t = 0;
  if (millis() - t >= 500) {
    t = millis();
    Serial2.printf("HOLA %lu\n", (unsigned long)n);
    Serial.printf("Enviado: HOLA %lu\n", (unsigned long)n);
    ++n;
  }
  // Con el puente GPIO17 -> GPIO16 en este mismo ESP32, lo enviado vuelve aquí.
  static String linea;
  while (Serial2.available()) {
    const char c = Serial2.read();
    if (c == '\n') { Serial.printf("   Recibido: %s\n", linea.c_str()); linea = ""; }
    else linea += c;
  }
}
