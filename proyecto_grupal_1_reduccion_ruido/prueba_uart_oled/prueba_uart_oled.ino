/* PRUEBA AISLADA UART + OLED, ESP32-S3, Arduino-ESP32 3.x.
   Nodo1 del ZIP development: TX GPIO17 -> S3 RX GPIO16; GND comun.
   UART 921600/8N1. OLED SSD1306 128x64: SDA8 SCL9, 3.3V.
   Bibliotecas: Adafruit SSD1306, Adafruit GFX Library y dependencias.
   No usa filtros, PWM ni tareas propias. Apagar amplificador durante esta prueba.
   Nodo1 USB921600, Nueva linea: fuente sint / tramas on.
   Consola S3 opcional USB115200. La OLED funciona sin monitor USB.
   Reiniciar S3 pone contadores en cero. No modificar nodo1.
*/
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <stdint.h>
#include <string.h>

// BEGIN PARSER
// Formato original v3: A5 5A, cabecera92, muestras int16 y referencia opcional.
struct RxV3 {
  uint8_t data[92+4*2048+4]{};
  unsigned used=0;
  uint32_t ok=0,crcErrors=0,headerErrors=0,seq=0;
  uint16_t samples=0,flags=0;
  int16_t first=0,minValue=0,maxValue=0;
  static uint16_t u16(const uint8_t*p){return uint16_t(p[0])|(uint16_t(p[1])<<8);}
  static uint32_t u32(const uint8_t*p){return u16(p)|(uint32_t(u16(p+2))<<16);}
  static uint32_t crc(const uint8_t*p,unsigned n){
    uint32_t c=0xffffffffu;
    while(n--){c^=*p++;for(int k=0;k<8;k++)c=(c>>1)^((c&1)?0xedb88320u:0);}
    return ~c;
  }
  void discard(unsigned n){memmove(data,data+n,used-n);used-=n;}
  void clearPartial(){used=0;}
  bool push(uint8_t b){
    if(used==sizeof(data))discard(1);
    data[used++]=b;
    bool accepted=false;
    for(;;){
      if(used<2)return accepted;
      if(data[0]!=0xa5||data[1]!=0x5a){discard(1);continue;}
      if(used<4)return accepted;
      if(data[2]!=3||data[3]!=92){headerErrors++;discard(1);continue;}
      if(used<12)return accepted;
      unsigned n=u16(data+8);
      if(n==0||n>2048){headerErrors++;discard(1);continue;}
      uint16_t f=u16(data+10);
      unsigned length=92+2*n*((f&64)?2:1)+4;
      if(used<length)return accepted;
      if(crc(data+2,length-6)!=u32(data+length-4)){
        crcErrors++;discard(1);continue;
      }
      seq=u32(data+4);samples=n;flags=f;
      first=minValue=maxValue=int16_t(u16(data+92));
      for(unsigned i=1;i<n;i++){
        int16_t x=int16_t(u16(data+92+2*i));
        if(x<minValue)minValue=x;if(x>maxValue)maxValue=x;
      }
      ok++;accepted=true;discard(length);
    }
  }
};
// END PARSER

HardwareSerial uartNodo1(1);
Adafruit_SSD1306 oled(128,64,&Wire,-1,100000,100000);
RxV3 rx;
bool oledOK=false;
uint32_t totalBytes=0,lastByteMs=0,lastFrameMs=0,bytesPerSecond=0;
uint8_t recent[4]{};
unsigned recentCount=0;

void showStatus(){
  uint32_t now=millis();
  const char* status=rx.ok&&uint32_t(now-lastFrameMs)<1000?"UART OK / CRC OK":
    totalBytes&&uint32_t(now-lastByteMs)<1000?"BYTES, SIN TRAMA":
    totalBytes?"SIN DATOS RECIENTES":"SIN BYTES UART";
  if(oledOK){
    oled.clearDisplay();oled.setTextSize(1);oled.setTextColor(SSD1306_WHITE);oled.setCursor(0,0);
    oled.println(status);
    oled.print("RX16 921600 ");oled.print(now/1000);oled.println("s");
    oled.print("Bytes:");oled.println(totalBytes);
    oled.print("B/s:");oled.print(bytesPerSecond);oled.print(" OK:");oled.println(rx.ok);
    oled.print("CRC:");oled.print(rx.crcErrors);oled.print(" H:");oled.println(rx.headerErrors);
    oled.print("Seq:");oled.print(rx.seq);oled.print(" N:");oled.println(rx.samples);
    oled.print("Min:");oled.print(rx.minValue);oled.print(" M:");oled.println(rx.maxValue);
    oled.print("Hex:");
    for(unsigned i=0;i<recentCount;i++){if(recent[i]<16)oled.print('0');oled.print(recent[i],HEX);oled.print(' ');}
    oled.display();
  }
  // No esperar a que el PC abra la consola.
  if(Serial){
    Serial.printf("%s bytes=%lu B/s=%lu validas=%lu CRC=%lu cabecera=%lu seq=%lu N=%u flags=0x%02X muestra0=%d min=%d max=%d\n",
      status,(unsigned long)totalBytes,(unsigned long)bytesPerSecond,(unsigned long)rx.ok,
      (unsigned long)rx.crcErrors,(unsigned long)rx.headerErrors,(unsigned long)rx.seq,
      rx.samples,rx.flags,rx.first,rx.minValue,rx.maxValue);
  }
}
void setup(){
  // Mantener ambas salidas de audio bajas: esta prueba NO reproduce sonido.
  pinMode(17,OUTPUT);digitalWrite(17,LOW);pinMode(18,OUTPUT);digitalWrite(18,LOW);
  Serial.begin(115200);
  Wire.begin(8,9,100000);Wire.setTimeOut(30);
  for(uint8_t address=0x3c;address<=0x3d;address++){
    Wire.beginTransmission(address);
    if(Wire.endTransmission()==0){oledOK=oled.begin(SSD1306_SWITCHCAPVCC,address,true,false);break;}
  }
  // Absorbe bytes mientras se actualiza la pantalla a 100 kHz.
  uartNodo1.setRxBufferSize(32768);
  uartNodo1.begin(921600,SERIAL_8N1,16,15);
  showStatus();
}
void loop(){
  if(rx.used&&uint32_t(millis()-lastByteMs)>200)rx.clearPartial();
  unsigned budget=16384; // actualizar OLED aunque exista trafico continuo
  while(budget--&&uartNodo1.available()){
    uint8_t b=uartNodo1.read();totalBytes++;lastByteMs=millis();
    if(recentCount<4)recent[recentCount++]=b;
    else {memmove(recent,recent+1,3);recent[3]=b;}
    if(rx.push(b))lastFrameMs=millis();
  }
  static uint32_t previousMs=0,previousBytes=0,lastScreen=0;
  uint32_t now=millis();
  if(uint32_t(now-previousMs)>=1000){
    bytesPerSecond=uint32_t(uint64_t(totalBytes-previousBytes)*1000/(now-previousMs));
    previousBytes=totalBytes;previousMs=now;
  }
  if(uint32_t(now-lastScreen)>=500){lastScreen=now;showStatus();}
  delay(1);
}
