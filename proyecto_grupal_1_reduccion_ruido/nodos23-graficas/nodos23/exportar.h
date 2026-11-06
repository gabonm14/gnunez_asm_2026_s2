// Se incluye en nodos.cpp: usa la captura y el motor FFT de su núcleo.
#include <stdarg.h>
#include "espectros.h"

static evidencia::Espectros espectros;
struct JsonExportacion {
  char datos[3000]{};
  size_t usados=0;
  bool valido=true;
  void agregar(const char* formato,...) {
    if (!valido) return;
    va_list args;
    va_start(args,formato);
    int n=vsnprintf(datos+usados,sizeof(datos)-usados,formato,args);
    va_end(args);
    if (n<0 || size_t(n)>=sizeof(datos)-usados) { valido=false; return; }
    usados+=n;
  }
  void numero(double v) {
    if (std::isnan(v)) agregar("null");
    else if (std::isinf(v)) agregar(v>0?"\"+inf\"":"\"-inf\"");
    else agregar("%.10g",v);
  }
};
static double razonDb(double senal,double error) {
  if (senal==0) return NAN;
  return error==0 ? INFINITY:10*log10(senal/error);
}
static void describir(JsonExportacion& json) {
  const auto& m=trabajo.m;
  const double snrIn=razonDb(m.es,m.errorIn);
  const unsigned bytes=trabajo.muestras*sizeof(ParPCM)+sizeof(espectros.dbHz);
  json.agregar("{\"schema\":1,\"firmware\":\"nodos23-export-1\",\"fs_hz\":%d,",FS);
  json.agregar("\"n_samples\":%d,\"capture_id\":%lu,\"duration_s\":%.6f,",trabajo.muestras,
    (unsigned long)trabajo.captura,trabajo.muestras/double(FS));
  json.agregar("\"finish\":\"%s\",\"payload_bytes\":%u,",trabajo.nota,bytes);
  json.agregar("\"sample_fields\":[\"fir\",\"fft\",\"mezcla\",\"referencia\"],\"invalid_reference\":-32768,");
  json.agregar("\"reference_samples\":%lu,\"energy_samples\":%lu,\"reference_pct\":%.6f,",
    (unsigned long)m.n,(unsigned long)m.nUtil,100.*m.n/trabajo.muestras);
  json.agregar("\"nfft\":%d,\"hop\":%d,\"n_bins\":%d,\"window\":\"hann_periodica\",",N,H,K);
  json.agregar("\"spectrum_frames\":%u,\"spectrum_scope\":\"%s\",",espectros.marcos,
    espectros.conReferencia?"referencia_comun":"captura_sin_referencia_completa");
  json.agregar("\"spectrum_fields\":[\"referencia\",\"mezcla\",\"fir\",\"fft\"],");
  json.agregar("\"spectrum_unit\":\"dB re 1 codigo_ADC^2/Hz\",\"spectrum_floor_db\":-200,");
  json.agregar("\"fir_delay_compensated_samples\":%d,\"spectral_alpha\":1.5,\"spectral_floor\":0.05,",RET);
  json.agregar("\"counters_delta\":{\"crc\":%lu,\"lost\":%lu,\"queue\":%lu,\"restarts\":%lu},",
    (unsigned long)(trabajo.fin.crc-trabajo.inicio.crc),
    (unsigned long)(trabajo.fin.perdidas-trabajo.inicio.perdidas),
    (unsigned long)(trabajo.fin.cola-trabajo.inicio.cola),
    (unsigned long)(trabajo.fin.reinicios-trabajo.inicio.reinicios));
  json.agregar("\"metrics\":{\"entrada\":{\"mse\":"); json.numero(m.n?m.errorIn/m.n:NAN);
  json.agregar(",\"snr_db\":"); json.numero(snrIn); json.agregar("}");
  for (int k=0;k<2;++k) {
    double snr=razonDb(m.es,m.error[k]);
    json.agregar(",\"%s\":{\"mse\":",k?"fft":"fir"); json.numero(m.n?m.error[k]/m.n:NAN);
    json.agregar(",\"snr_db\":"); json.numero(snr);
    json.agregar(",\"delta_snr_db\":"); json.numero(snr-snrIn);
    json.agregar(",\"useful_energy_pct\":"); json.numero(m.baseUtil?100*m.util[k]/m.baseUtil:NAN);
    json.agregar(",\"pwm_clips\":%lu}",(unsigned long)m.recortePWM[k]);
  }
  json.agregar("}}\n");
}
static uint32_t actualizarCRC(uint32_t c,const uint8_t* p,size_t n) {
  for (size_t i=0;i<n;++i) c=rx.tabla[(c^p[i])&255]^(c>>8);
  return c;
}
static bool enviarBytes(const void* origen,size_t n,uint32_t& crcEnvio) {
  const auto* p=static_cast<const uint8_t*>(origen);
  while (n) {
    size_t cantidad=std::min(n,size_t(256));
    if (Serial.write(p,cantidad)!=cantidad) return false;
    crcEnvio=actualizarCRC(crcEnvio,p,cantidad);
    p+=cantidad; n-=cantidad;
    vTaskDelay(1);
  }
  return true;
}
static void exportar() {
  // Un único escritor durante toda la transferencia; la consola usa el mismo mutex.
  xSemaphoreTake(mutexSerial,portMAX_DELAY);
  if (trabajo.modo!=LISTA || trabajo.muestras==0) {
    Serial.println("ASM23_ERROR Requiere LISTA: grabar con g y esperar a que termine.");
    xSemaphoreGive(mutexSerial);
    return;
  }
  pausaExportar=true;
  while (!uartPausada.load()) vTaskDelay(1);
  Salto* pendiente;
  while (xQueueReceive(listos,&pendiente,0)==pdTRUE) xQueueSend(libres,&pendiente,0);
  trabajo.modo=EXPORTANDO; publicar();
  // La referencia incompleta se excluye por ventanas enteras, sin unir segmentos.
  espectros.calcular(audio::clip,trabajo.muestras,espectral,[]{vTaskDelay(1);});
  JsonExportacion json;
  describir(json);
  if (json.valido) {
    Serial.print("\nASM23_EXPORT_V1\n");
    uint32_t c=~0u;
    bool ok=enviarBytes(json.datos,json.usados,c)
      && enviarBytes(audio::clip,trabajo.muestras*sizeof(ParPCM),c)
      && enviarBytes(espectros.dbHz,sizeof(espectros.dbHz),c);
    if (ok) {
      c=~c;
      Serial.write(reinterpret_cast<const uint8_t*>(&c),sizeof c);
      Serial.print("\nASM23_END\n");
    }
    Serial.flush();
  } else Serial.println("ASM23_ERROR Metadatos demasiado largos.");
  // El siguiente salto fresco vuelve a calentar los filtros tras la descarga.
  espectral.reiniciar(); hayPrevio=false; wolaCaliente=false;
  trabajo.modo=LISTA; publicar();
  pausaExportar=false;
  while (uartPausada.load()) vTaskDelay(1);
  xSemaphoreGive(mutexSerial);
}
