/* Taller 3, punto 2. ESP32-S3, Arduino-ESP32 3.3.2 (ESP-IDF 5.5).
 * PWM LEDC, canal 0 exclusivo; no usar analogWrite/tone/fade en este canal.
 * Las tablas son periódicas y la ISR solo lee RAM y actualiza registros.
 */
#include <Arduino.h>
#include <driver/ledc.h>
#include <hal/ledc_ll.h>
#include <soc/ledc_struct.h>
#include "tablas.h"
#if !CONFIG_IDF_TARGET_ESP32S3
#error "Este firmware requiere ESP32-S3. No seleccionar ESP32 clasico."
#endif

constexpr int PWM_PIN = 17; // GPIO4, no numero fisico de patilla. Verificar placa.
constexpr uint32_t PWM_HZ = 256000;
static DRAM_ATTR uint8_t samples[MODE_COUNT][TABLE_N];
static volatile uint32_t activeMode = 0;
static uint32_t sampleIndex = 0;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static hw_timer_t* sampleTimer = nullptr;

void ARDUINO_ISR_ATTR onSample() {
  // APIs LL verificadas contra ESP-IDF 5.5.1; no locks del driver ni flotantes.
  portENTER_CRITICAL_ISR(&mux);
  const uint32_t duty = samples[activeMode][sampleIndex];
  if (++sampleIndex == TABLE_N) sampleIndex = 0;
  ledc_ll_set_duty_int_part(&LEDC, LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
  ledc_ll_set_duty_start(&LEDC, LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
  ledc_ll_ls_channel_update(&LEDC, LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
  portEXIT_CRITICAL_ISR(&mux);
}

void selectMode(uint32_t mode) {
  portENTER_CRITICAL(&mux);
  activeMode = mode;
  sampleIndex = 0;
  portEXIT_CRITICAL(&mux);
  Serial.printf("Modo %lu: %s\n", (unsigned long)mode, MODE_NAMES[mode]);
}

void showMenu() {
  Serial.println("Enviar un digito 0..8 (sin importar fin de linea); ? muestra menu.");
  for (uint32_t m = 0; m < MODE_COUNT; ++m)
    Serial.printf("%lu: %s\n", (unsigned long)m, MODE_NAMES[m]);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  memcpy(samples, TABLES, sizeof(samples));
  ledc_timer_config_t tc = {};
  tc.speed_mode = LEDC_LOW_SPEED_MODE;
  tc.duty_resolution = LEDC_TIMER_8_BIT;
  tc.timer_num = LEDC_TIMER_0;
  tc.freq_hz = PWM_HZ;
  tc.clk_cfg = LEDC_USE_APB_CLK; // 80 MHz: no usar el XTAL de 40 MHz.
  ESP_ERROR_CHECK(ledc_timer_config(&tc));
  ledc_channel_config_t cc = {};
  cc.gpio_num = PWM_PIN;
  cc.speed_mode = LEDC_LOW_SPEED_MODE;
  cc.channel = LEDC_CHANNEL_0;
  cc.intr_type = LEDC_INTR_DISABLE;
  cc.timer_sel = LEDC_TIMER_0;
  cc.duty = 128; // Reposo: 1.65 V nominal despues del RC.
  cc.hpoint = 0;
  ESP_ERROR_CHECK(ledc_channel_config(&cc));
  // 2 MHz / 125 = 16000 muestras/s. Evita redondear 62.5 us a 62 o 63.
  sampleTimer = timerBegin(2000000);
  if (!sampleTimer) { Serial.println("ERROR creando temporizador"); while(true) delay(1000); }
  if (timerGetFrequency(sampleTimer) != 2000000) {
    Serial.println("ERROR: reloj de muestras inesperado"); while(true) delay(1000);
  }
  timerAttachInterrupt(sampleTimer, &onSample);
  timerAlarm(sampleTimer, 125, true, 0);
  Serial.printf("fs=%lu Hz; PWM real reportado=%lu Hz; GPIO=%d\n",
                (unsigned long)FS_HZ,
                (unsigned long)ledc_get_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_0), PWM_PIN);
  showMenu(); // Inicia en reposo hasta seleccionar un tono.
}

void loop() {
  while (Serial.available()) {
    const char c = Serial.read();
    if (c >= '0' && c <= '8') selectMode(c - '0');
    else if (c == '?') showMenu();
  }
  delay(1); // Solo consola; no determina la temporizacion de las muestras.
}
