// PWM del montaje probado: GPIO17/18, RC independientes y selector DPDT.
// El temporizador solo lee RAM interna. La captura está congelada al reproducir.
#pragma once
#include <Arduino.h>
#include <driver/ledc.h>
#include <hal/ledc_ll.h>
#include <soc/ledc_struct.h>
#include <esp_heap_caps.h>

struct ParPCM { int16_t a,b,x,ref; };
static_assert(sizeof(ParPCM)==8, "Formato PCM de cuatro canales");
namespace audio {
static ParPCM* clip=nullptr;  // memoria interna direccionable por la ISR
static int capacidad=0;
static volatile int posicion=0, fin=0;
static volatile bool activo=false;
static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;

static inline __attribute__((always_inline)) void duty(ledc_channel_t canal,int valor) {
  ledc_ll_set_duty_int_part(&LEDC,LEDC_LOW_SPEED_MODE,canal,valor);
  ledc_ll_set_duty_start(&LEDC,LEDC_LOW_SPEED_MODE,canal);
  ledc_ll_ls_channel_update(&LEDC,LEDC_LOW_SPEED_MODE,canal);
}
static inline __attribute__((always_inline)) int aPwm(int x) {
  int d=256+x/4; // misma ganancia en A y B; altavoz se regula con el PAM
  return d<0 ? 0 : (d>511 ? 511 : d);
}
static void IRAM_ATTR tick() {
  portENTER_CRITICAL_ISR(&mux);
  if (activo) {
    if (posicion<fin) {
      ParPCM s=clip[posicion]; posicion=posicion+1;
      duty(LEDC_CHANNEL_0,aPwm(s.a)); duty(LEDC_CHANNEL_1,aPwm(s.b));
    } else {
      duty(LEDC_CHANNEL_0,256); duty(LEDC_CHANNEL_1,256);
      activo=false;
    }
  }
  portEXIT_CRITICAL_ISR(&mux);
}
inline bool sonando() {
  portENTER_CRITICAL(&mux); bool v=activo; portEXIT_CRITICAL(&mux); return v;
}
inline void reproducir(int n) {
  portENTER_CRITICAL(&mux); posicion=0; fin=n; activo=n>0; portEXIT_CRITICAL(&mux);
}
inline void parar() {
  portENTER_CRITICAL(&mux);
  activo=false; duty(LEDC_CHANNEL_0,256); duty(LEDC_CHANNEL_1,256);
  portEXIT_CRITICAL(&mux);
}
inline bool inicio() {
  ledc_timer_config_t t={};
  t.speed_mode=LEDC_LOW_SPEED_MODE; t.duty_resolution=LEDC_TIMER_9_BIT;
  t.timer_num=LEDC_TIMER_0; t.freq_hz=156250; t.clk_cfg=LEDC_USE_APB_CLK;
  if (ledc_timer_config(&t)!=ESP_OK) return false;
  for (int i=0;i<2;++i) {
    ledc_channel_config_t c={};
    c.gpio_num=17+i; c.speed_mode=t.speed_mode; c.channel=(ledc_channel_t)i;
    c.timer_sel=t.timer_num; c.duty=256;
    if (ledc_channel_config(&c)!=ESP_OK) return false;
  }
  auto* reloj=timerBegin(2000000);
  if (!reloj || timerGetFrequency(reloj)!=2000000) return false;
  timerAttachInterrupt(reloj,&tick);
  timerAlarm(reloj,125,true,0);
  return true;
}
// Reserva al final del arranque, dejando memoria para el sistema y para el USB.
inline void reservar() {
  const uint32_t caps=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT;
  size_t libre=heap_caps_get_free_size(caps);
  size_t maximo=std::min(heap_caps_get_largest_free_block(caps),libre>32768?libre-32768:0);
  int saltos=std::min(size_t(125),maximo/(sizeof(ParPCM)*dsp::H)); // hasta 4 s
  for (;saltos>=1;--saltos) {
    clip=(ParPCM*)heap_caps_malloc(saltos*dsp::H*sizeof(ParPCM),caps);
    if (clip) { capacidad=saltos*dsp::H; return; }
  }
}
}
