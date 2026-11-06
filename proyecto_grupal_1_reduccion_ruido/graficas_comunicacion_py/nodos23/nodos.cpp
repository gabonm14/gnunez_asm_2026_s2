#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#include <atomic>
#include "dsp.h"
#include "trama.h"
#include "audio.h"
#if !CONFIG_IDF_TARGET_ESP32S3 || CONFIG_FREERTOS_UNICORE
#error "Seleccionar ESP32S3 Dev Module con ambos nucleos y Arduino-ESP32 3.3.2."
#endif

using namespace dsp;
using namespace uartv3;
static Receptor rx;
static Temporal temporal;
static Espectral espectral;
static QueueHandle_t libres, listos, comandos;
static SemaphoreHandle_t mutexSerial;
// La descarga congela el procesamiento, pero el núcleo 0 sigue vaciando UART1.
static std::atomic<bool> pausaExportar{false}, uartPausada{false};
static Salto pool[4], armado;
static std::atomic<uint32_t> frames{0}, crc{0}, perdidas{0}, reinicios{0}, descartes{0}, malas{0}, avisosADC{0};
static std::atomic<uint32_t> usFIR{0}, nUltimo{0};
struct CabeceraVista {
  uint32_t seq, diagnostico;
  uint16_t estado;
  uint8_t tipos, confianza;
  float corte;
};
static CabeceraVista cabPublicada{};
static portMUX_TYPE muxCab=portMUX_INITIALIZER_UNLOCKED;
static uint32_t ultimaSeq, ultimoDesborde;
static bool haySeq=false, discontinuo=true;
static int llenado=0;

static void nuevaTrama(const uint8_t* p) {
  const uint32_t seq=u32(p+4), desborde=u32(p+16);
  const uint16_t estado=u16(p+10);
  bool salto=false;
  if (haySeq) {
    const uint32_t avance=seq-ultimaSeq;
    if (avance==0) return; // duplicado: no insertar dos veces las mismas muestras
    if (avance>0x7fffffffu) { ++reinicios; salto=true; }
    else if (avance>1) { perdidas+=avance-1; salto=true; }
    salto |= desborde!=ultimoDesborde;
  }
  ultimoDesborde=desborde; ultimaSeq=seq; haySeq=true;
  if (estado&4) { ++avisosADC; salto=true; }
  if (salto) { llenado=0; temporal=Temporal{}; discontinuo=true; }
  int n=u16(p+8);
  CabeceraVista cab{seq,u32(p+24),estado,p[28],uint8_t(p[29]&1),f32(p+32)};
  portENTER_CRITICAL(&muxCab); cabPublicada=cab; portEXIT_CRITICAL(&muxCab);
  ++frames; nUltimo=n;
  if (pausaExportar.load()) return;
  uint32_t inicio=micros();
  for (int j=0;j<n;++j) {
    int16_t x=(int16_t)u16(p+CAB+2*j);
    int16_t r=estado&64 ? (int16_t)u16(p+CAB+2*(n+j)) : SIN_REF;
    temporal.muestra(armado,llenado++,x,r);
    if (llenado<H) continue;
    armado.finUtil=(p[29]&1) ? f32(p+32) : NAN;
    armado.discontinuo=discontinuo;
    Salto* s;
    if (xQueueReceive(libres,&s,0)==pdTRUE) {
      *s=armado;
      xQueueSend(listos,&s,0); // un hueco garantizado por la reserva en libres
      discontinuo=false;
    } else { ++descartes; discontinuo=true; }
    llenado=0;
  }
  usFIR=micros()-inicio;
}
static void tareaUART(void*) {
  uint8_t bytes[CHUNK];
  for (;;) {
    if (pausaExportar.load()) {
      if (!uartPausada.load()) {
        llenado=0; temporal=Temporal{}; discontinuo=true;
        uartPausada=true;
      }
    } else uartPausada=false;
    int n=std::min(int(Serial1.available()),CHUNK);
    if (n<=0) { vTaskDelay(1); continue; }
    size_t leidos=Serial1.read(bytes,n);  // leer lo ya disponible, sin esperar una trama
    rx.agregar(bytes,leidos,nuevaTrama);
    crc=rx.crcMal; malas=rx.cabMal;
  }
}

enum Modo { ESPERA, GRABANDO, LISTA, ESCUCHANDO, EXPORTANDO, ESPERANDO_REF };
static const char* nombres[]={"ESPERA","GRABANDO","LISTA","REPRODUCIENDO","EXPORTANDO","ESPERANDO_REF"};
struct Medidas {
  double es=0, errorIn=0, error[2]{}, util[2]{}, baseUtil=0;
  uint32_t n=0, nUtil=0, recortePWM[2]{};
  void sumar(int x,int r,float a,float b,float limpiaA,float limpiaB,bool utilOK) {
    if (r==SIN_REF) return;
    double d=x-r, da=a-r, db=b-r;
    es+=double(r)*r; errorIn+=d*d;
    error[0]+=da*da; error[1]+=db*db; ++n;
    if (utilOK && std::isfinite(limpiaA)) {
      baseUtil+=double(r)*r; util[0]+=double(limpiaA)*limpiaA;
      util[1]+=double(limpiaB)*limpiaB; ++nUtil;
    }
  }
};
struct Contadores {
  uint32_t crc, perdidas, cola, reinicios;
};
static Contadores contadores() {
  return {crc.load(),perdidas.load(),descartes.load(),reinicios.load()};
}
struct Vista {
  Modo modo=ESPERA;
  int muestras=0;
  Medidas m;
  const char* nota="g para grabar";
  uint32_t usFFT=0;
  uint32_t captura=0;
  Contadores inicio{}, fin{};
};
static Vista trabajo, publicada;
static portMUX_TYPE muxVista=portMUX_INITIALIZER_UNLOCKED;
static Salto previo;
static float y[H], limpiaY[H];
static bool hayPrevio=false, wolaCaliente=false;
static unsigned omitir=0;
static bool exigirReferencia=false;
static uint32_t numeroCaptura=0;
static void exportar();
static void publicar() {
  portENTER_CRITICAL(&muxVista); publicada=trabajo; portEXIT_CRITICAL(&muxVista);
}
static void cerrar(const char* causa) {
  if (trabajo.modo==GRABANDO) trabajo.fin=contadores();
  trabajo.modo=trabajo.muestras ? LISTA : ESPERA;
  trabajo.nota=causa;
}
static void orden(char c) {
  if (c=='x') { exportar(); return; }
  if (c=='s') { audio::parar(); cerrar("Detenido"); return; }
  if (c=='p') {
    if (trabajo.modo==LISTA && trabajo.muestras) {
      audio::reproducir(trabajo.muestras);
      trabajo.modo=ESCUCHANDO; trabajo.nota="Selector A/B";
    } else trabajo.nota="p requiere LISTA";
    return;
  }
  if (c=='g' || c=='r') {
    if (trabajo.modo==ESCUCHANDO || trabajo.modo==GRABANDO || trabajo.modo==ESPERANDO_REF) {
      trabajo.nota="Usar s primero"; return;
    }
    trabajo=Vista{}; trabajo.captura=++numeroCaptura;
    trabajo.inicio=contadores(); trabajo.fin=trabajo.inicio;
    exigirReferencia=c=='r';
    trabajo.modo=exigirReferencia ? ESPERANDO_REF : GRABANDO;
    trabajo.nota=exigirReferencia ? "Esperando referencia" : "PWM en silencio";
    omitir=2;  // no guardar colas de la ventana anterior a la orden
  }
}
static int16_t pcm(float f) {
  return int16_t(lroundf(std::max(-32768.f,std::min(32767.f,f))));
}
static void procesar(const Salto& actual) {
  if (actual.discontinuo) {
    if (trabajo.modo==GRABANDO && trabajo.muestras) cerrar("CORTE: UART o cola");
    espectral.reiniciar(); hayPrevio=false; wolaCaliente=false;
  }
  if (hayPrevio) {
    uint32_t inicio=micros();
    bool utilOK=espectral.procesar(previo,actual,y,limpiaY);
    trabajo.usFFT=micros()-inicio;
    if (trabajo.modo==ESPERANDO_REF && wolaCaliente) {
      if (omitir) --omitir;
      else if (utilOK) {
        trabajo.modo=GRABANDO; trabajo.nota="Con referencia";
        trabajo.inicio=contadores(); trabajo.fin=trabajo.inicio;
      }
    }
    if (trabajo.modo==GRABANDO && exigirReferencia && !utilOK)
      cerrar("Fin tramo referencia");
    if (trabajo.modo==GRABANDO && wolaCaliente) {
      if (omitir) --omitir;
      else {
        for (int i=0;i<H;++i) {
          // El FIR lineal representa x[n] 40 muestras más tarde. Tomamos
          // esas 40 del salto siguiente para alinear A, B y referencia.
          int k=i+RET;
          const Salto& fuente=k<H ? previo : actual;
          k%=H;
          auto a=pcm(fuente.fir[k]), b=pcm(y[i]);
          audio::clip[trabajo.muestras++]={a,b,previo.x[i],previo.ref[i]};
          if (a/4 < -256 || a/4 > 255) ++trabajo.m.recortePWM[0];
          if (b/4 < -256 || b/4 > 255) ++trabajo.m.recortePWM[1];
          trabajo.m.sumar(previo.x[i],previo.ref[i],a,b,fuente.firLimpia[k],limpiaY[i],utilOK);
        }
        if (trabajo.muestras==audio::capacidad) cerrar("Captura completa");
      }
    }
    wolaCaliente=true;
  }
  previo=actual; hayPrevio=true;
}
static void tareaEspectral(void*) {
  uint32_t ultimo=millis();
  for (;;) {
    char c;
    while (xQueueReceive(comandos,&c,0)==pdTRUE) {
      orden(c);
      if (c=='g' || c=='r') ultimo=millis();
    }
    if (trabajo.modo==ESCUCHANDO && !audio::sonando()) cerrar("Fin de escucha");
    Salto* s;
    if (xQueueReceive(listos,&s,pdMS_TO_TICKS(5)+1)==pdTRUE) {
      procesar(*s);
      xQueueSend(libres,&s,0);
      ultimo=millis();
    } else if (trabajo.modo==GRABANDO && millis()-ultimo>1000) {
      cerrar("CORTE: sin tramas");
    }
    publicar();
  }
}

#include "exportar.h"

static Adafruit_SSD1306 oled(128,64,&Wire,-1);
static bool oledOK=false, invertir=false;
static double db(double sig,double err) {
  if (sig==0) return NAN;
  return err==0 ? INFINITY : 10*log10(sig/err);
}
static void numero(Print& out,double v,int dig=1) {
  if (std::isnan(v)) out.print("N/D");
  else if (std::isinf(v)) out.print(v>0 ? "+inf" : "-inf");
  else out.print(v,dig);
}
static void informe(const Vista& v) {
  Serial.printf("%s %.3f/%.3f s | %s | validas %lu CRC %lu cab %lu perdidas %lu reinicios %lu cola %lu ADC! %lu\n",
    nombres[v.modo],v.muestras/double(FS),audio::capacidad/double(FS),v.nota,
    (unsigned long)frames.load(),(unsigned long)crc.load(),(unsigned long)malas.load(),
    (unsigned long)perdidas.load(),(unsigned long)reinicios.load(),(unsigned long)descartes.load(),(unsigned long)avisosADC.load());
  CabeceraVista cab;
  portENTER_CRITICAL(&muxCab); cab=cabPublicada; portEXIT_CRITICAL(&muxCab);
  if (frames.load()) {
    Serial.printf("seq %lu | estado 0x%02x (%s referencia) | diagnostico #%lu tipos 0x%02x | banda util hasta ",
      (unsigned long)cab.seq,cab.estado,cab.estado&64?"con":"sin",(unsigned long)cab.diagnostico,cab.tipos);
    numero(Serial,(cab.confianza && cab.corte>0 && cab.corte<7600) ? cab.corte : 1500);
    Serial.println(" Hz");
  }
  Serial.printf("Calculo: UART+FIR (sin CRC) %lu us/%lu muestras | FFT/WOLA %lu us/512 | muestras con ref %lu | ref energia %lu\n",
    (unsigned long)usFIR.load(),(unsigned long)nUltimo.load(),(unsigned long)v.usFFT,(unsigned long)v.m.n,(unsigned long)v.m.nUtil);
  for (int k=0;k<2;++k) {
    const Medidas& m=v.m;
    double antes=db(m.es,m.errorIn), despues=db(m.es,m.error[k]);
    Serial.print(k==0?"A FIR | MSE ":"B FFT | MSE "); numero(Serial,m.n?m.error[k]/m.n:NAN,2);
    Serial.print(" | SNRin "); numero(Serial,antes); Serial.print(" dB | SNRout "); numero(Serial,despues);
    Serial.print(" dB | delta "); numero(Serial,despues-antes);
    Serial.print(" dB | energia util "); numero(Serial,m.baseUtil?100*m.util[k]/m.baseUtil:NAN);
    Serial.printf(" %% | recortes PWM %lu\n",(unsigned long)m.recortePWM[k]);
  }
}
static void pantalla(const Vista& v) {
  if (!oledOK) return;
  int k=((digitalRead(7)==LOW)!=invertir) ? 0 : 1;
  oled.clearDisplay(); oled.setCursor(0,0);
  oled.println(nombres[v.modo]); oled.println(k?"B: FFT / GPIO18":"A: FIR / GPIO17");
  oled.print(v.muestras/float(FS),2); oled.print("/"); oled.print(audio::capacidad/float(FS),2); oled.println(" s");
  oled.print("MSE "); numero(oled,v.m.n?v.m.error[k]/v.m.n:NAN);
  oled.print("\nSNR in  "); numero(oled,db(v.m.es,v.m.errorIn)); oled.println(" dB");
  oled.print("SNR out "); numero(oled,db(v.m.es,v.m.error[k])); oled.println(" dB");
  oled.print("E util  "); numero(oled,v.m.baseUtil?100*v.m.util[k]/v.m.baseUtil:NAN); oled.println("%");
  oled.println(v.nota); oled.display();
}
static void fatal(const char* msg) { for (;;) { Serial.println(msg); delay(2000); } }
static void ayuda() {
  Serial.println("r: esperar referencia y grabar un tramo continuo valido");
  Serial.println("g: grabar ambas (reemplaza el clip) | s: detener | p: reproducir ambas desde inicio");
  Serial.println("e: estado y metricas | x: descargar captura binaria (usar Python) | i: invertir A/B | ?: ayuda");
}
void iniciarNodos() {
  Serial.begin(115200);
  mutexSerial=xSemaphoreCreateMutex();
  if (!mutexSerial) fatal("ERROR mutex serie");
  pinMode(7,INPUT_PULLUP);
  if (Wire.begin(8,9,400000)) {
    Wire.setTimeOut(30);
    for (uint8_t dir: {0x3c,0x3d}) {
      Wire.beginTransmission(dir);
      if (Wire.endTransmission()==0) { oledOK=oled.begin(SSD1306_SWITCHCAPVCC,dir,true,false); break; }
    }
    if (oledOK) { oled.setTextSize(1); oled.setTextColor(SSD1306_WHITE); }
  }
  if (Serial1.setRxBufferSize(16384)<16384) fatal("ERROR buffer UART");
  Serial1.begin(921600,SERIAL_8N1,16,15);
  if (!Serial1) fatal("ERROR iniciando UART1");
  rx.iniciar(); espectral.iniciar();
  libres=xQueueCreate(4,sizeof(Salto*)); listos=xQueueCreate(4,sizeof(Salto*)); comandos=xQueueCreate(8,1);
  if (!libres || !listos || !comandos || !audio::inicio()) fatal("ERROR configurando colas/PWM");
  for (auto& s:pool) { Salto* p=&s; xQueueSend(libres,&p,0); }
  // Reservar pilas de ambas tareas antes de dimensionar el clip.
  if (xTaskCreatePinnedToCore(tareaUART,"UART FIR",6144,nullptr,3,nullptr,0)!=pdPASS ||
      xTaskCreatePinnedToCore(tareaEspectral,"FFT",8192,nullptr,3,nullptr,1)!=pdPASS)
    fatal("ERROR creando tareas");
  audio::reservar();
  if (!audio::capacidad) fatal("ERROR sin RAM para clip");
  ayuda();
  Serial.printf("Capacidad %.3f s para las cuatro pistas; SSD1306 %s. Envie e para estado.\n",
    audio::capacidad/double(FS),oledOK?"OK":"ausente");
}
void atenderConsola() {
  static uint32_t ultimaPantalla=0, anteriorUART=0;
  static int anteriorModo=-1;
  if (xSemaphoreTake(mutexSerial,0)!=pdTRUE) { delay(5); return; }
  bool pedir=false, pedirEstado=false;
  while (Serial.available()) {
    char c=Serial.read();
    if (c=='g' || c=='r' || c=='p' || c=='s' || c=='x') {
      if (xQueueSend(comandos,&c,0)!=pdTRUE) Serial.println("Cola de comandos llena; repetir.");
    } else if (c=='i') invertir=!invertir;
    else if (c=='e') pedir=true;
    else if (c=='q') pedirEstado=true;
    else if (c=='?') ayuda();
  }
  Vista v;
  portENTER_CRITICAL(&muxVista); v=publicada; portEXIT_CRITICAL(&muxVista);
  if (pedirEstado) {
    CabeceraVista cab;
    portENTER_CRITICAL(&muxCab); cab=cabPublicada; portEXIT_CRITICAL(&muxCab);
    Serial.printf("ASM23_STATUS {\"firmware\":\"nodos23-export-2\",\"mode\":\"%s\",\"capture_id\":%lu,\"n_samples\":%d,\"capacity\":%d,\"reference_samples\":%lu,\"live_reference\":%s,\"frames\":%lu}\n",
      nombres[v.modo],(unsigned long)v.captura,v.muestras,audio::capacidad,
      (unsigned long)v.m.n,(cab.estado&64)?"true":"false",(unsigned long)frames.load());
  }
  if (pedir || anteriorModo!=v.modo || millis()-anteriorUART>=3000) {
    informe(v); anteriorModo=v.modo; anteriorUART=millis();
  }
  xSemaphoreGive(mutexSerial);
  if (millis()-ultimaPantalla>=250) { pantalla(v); ultimaPantalla=millis(); }
  delay(2);
}
