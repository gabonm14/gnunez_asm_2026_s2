"""Descarga del S3 y representación de resultados calculados en el microcontrolador."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import struct
import sys
import time
import zlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

INICIO = b"ASM23_EXPORT_V1\n"
FINAL = b"\nASM23_END\n"
CAMPOS_MUESTRAS = ["fir", "fft", "mezcla", "referencia"]
CAMPOS_ESPECTROS = ["referencia", "mezcla", "fir", "fft"]
NOMBRES = {"referencia": "Referencia limpia", "mezcla": "Mezcla", "fir": "FIR", "fft": "FFT/IFFT"}
COLORES = {"referencia": "#222222", "mezcla": "#8B94A3", "fir": "#C36A16", "fft": "#007E87"}


def leer_exactos(fuente, cantidad, limite):
    datos = bytearray()
    while len(datos) < cantidad:
        if time.monotonic() > limite:
            raise TimeoutError("Transferencia incompleta. El clip puede descargarse otra vez con x.")
        parte = fuente.read(cantidad - len(datos))
        if not parte and isinstance(fuente, io.BytesIO):
            raise ValueError("El archivo está truncado.")
        datos.extend(parte)
    return bytes(datos)


def leer_linea(fuente, limite, maximo=4096):
    linea = bytearray()
    while len(linea) < maximo:
        b = leer_exactos(fuente, 1, limite)
        linea.extend(b)
        if b == b"\n":
            return bytes(linea)
    raise ValueError("Línea demasiado larga o datos fuera del protocolo.")


def recibir(fuente, timeout=120):
    limite = time.monotonic() + timeout
    while True:
        linea = leer_linea(fuente, limite)
        if linea == INICIO:
            break
        if linea.startswith(b"ASM23_ERROR"):
            raise ValueError(linea.decode("ascii", errors="replace").strip())
    cabecera = leer_linea(fuente, limite)
    meta = json.loads(cabecera)
    n = meta.get("n_samples", 0)
    bins = meta.get("n_bins", 0)
    if (meta.get("schema") != 1 or meta.get("fs_hz") != 16000
            or meta.get("nfft") != 1024 or bins != 513
            or meta.get("hop") != 512 or not 0 < n <= 64000
            or meta.get("sample_fields") != CAMPOS_MUESTRAS
            or meta.get("spectrum_fields") != CAMPOS_ESPECTROS
            or meta.get("invalid_reference") != -32768):
        raise ValueError("Formato de captura incompatible con este programa.")
    esperado = n * 8 + 4 * bins * 4
    if meta.get("payload_bytes") != esperado:
        raise ValueError("Longitud declarada incorrecta.")
    cuerpo = leer_exactos(fuente, esperado, limite)
    crc_bytes = leer_exactos(fuente, 4, limite)
    crc = struct.unpack("<I", crc_bytes)[0]
    if zlib.crc32(cuerpo, zlib.crc32(cabecera)) != crc:
        raise ValueError("CRC incorrecto. Repetí la descarga del clip.")
    if leer_exactos(fuente, len(FINAL), limite) != FINAL:
        raise ValueError("Falta el cierre de la transferencia.")
    muestras = np.frombuffer(cuerpo[:n * 8], dtype="<i2").reshape(n, 4).copy()
    espectros = np.frombuffer(cuerpo[n * 8:], dtype="<f4").reshape(4, bins).copy()
    # Comprobación de integridad del contador, sin recalcular métricas de señal.
    if int(np.count_nonzero(muestras[:, 3] != -32768)) != meta["reference_samples"]:
        raise ValueError("El contador de referencia no coincide con las muestras descargadas.")
    bruto = INICIO + cabecera + cuerpo + crc_bytes + FINAL
    return meta, muestras, espectros, bruto


def estado(puerto):
    puerto.write(b"q\n")
    limite = time.monotonic() + 6
    while True:
        linea = leer_linea(puerto, limite)
        if linea.startswith(b"ASM23_STATUS "):
            return json.loads(linea[len(b"ASM23_STATUS "):])


def abrir_puerto(nombre):
    import serial
    puerto = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=3)
    puerto.dtr = False
    puerto.rts = False
    puerto.port = nombre
    puerto.open()
    # Abrir un puente USB-UART puede reiniciar ciertas placas. Se abre antes de grabar.
    time.sleep(2)
    puerto.reset_input_buffer()
    return puerto


def adquirir(args):
    with abrir_puerto(args.puerto) as puerto:
        actual = estado(puerto)
        print(f"S3 conectado. Capacidad {actual['capacity'] / 16000:.3f} s.")
        print(f"Tramas recibidas {actual['frames']}. Referencia en la última trama: {actual['live_reference']}.")
        if args.descargar_existente:
            if actual["mode"] != "LISTA" or actual["n_samples"] == 0:
                raise ValueError("No hay un clip listo. Volvé a ejecutar sin --descargar-existente para grabar.")
        else:
            print("En el emisor y nodo 1 prepará la referencia de esta prueba; luego usá comp mezcla.")
            input("Cuando el diagnóstico esté estable, presioná Enter para grabar en el S3... ")
            puerto.reset_input_buffer()
            anterior = estado(puerto)
            if anterior["mode"] in ("GRABANDO", "REPRODUCIENDO"):
                raise ValueError("El S3 está ocupado. Terminá la operación con s y volvé a intentar.")
            if not anterior["live_reference"]:
                print("La última trama viene sin referencia. La captura podría tener cobertura parcial o nula.")
                if input("¿Grabar de todos modos? Escribí si para continuar: ").strip().lower() != "si":
                    raise ValueError("Captura cancelada. Revisá ref en el nodo 1.")
            puerto.write(b"g\n")
            limite = time.monotonic() + 15
            while time.monotonic() < limite:
                actual = estado(puerto)
                if actual["capture_id"] > anterior["capture_id"]:
                    if actual["mode"] == "LISTA":
                        break
                    if actual["mode"] == "ESPERA":
                        raise ValueError("La captura terminó vacía. Revisá las tramas UART del nodo 1.")
                time.sleep(0.2)
            else:
                raise TimeoutError("El S3 no terminó la captura. Revisá el estado con e.")
        print(f"Descargando {actual['n_samples']} muestras por señal a 115200 baudios...")
        puerto.write(b"x\n")
        return recibir(puerto)


def texto_numero(valor, decimales=2):
    if valor is None:
        return "N/D"
    if isinstance(valor, str):
        return valor
    return f"{valor:.{decimales}f}"


def filas_metricas(meta):
    m = meta["metrics"]
    filas = [["Entrada", m["entrada"]["mse"], m["entrada"]["snr_db"], None, None, None]]
    for clave in ("fir", "fft"):
        fila = m[clave]
        filas.append([NOMBRES[clave], fila["mse"], fila["snr_db"], fila["delta_snr_db"],
                      fila["useful_energy_pct"], fila["pwm_clips"]])
    return filas


def guardar_tablas(carpeta, meta, muestras, espectros):
    fs = meta["fs_hz"]
    with (carpeta / "muestras.csv").open("w", newline="", encoding="utf-8") as archivo:
        writer = csv.writer(archivo)
        writer.writerow(["indice", "tiempo_s", "referencia", "mezcla", "fir", "fft", "referencia_valida"])
        for i, (a, b, x, ref) in enumerate(muestras):
            valida = ref != -32768
            writer.writerow([i, f"{i/fs:.8f}", int(ref) if valida else "", int(x), int(a), int(b), int(valida)])
    with (carpeta / "espectros.csv").open("w", newline="", encoding="utf-8") as archivo:
        writer = csv.writer(archivo)
        writer.writerow(["frecuencia_hz"] + [c + "_db_codigo2_hz" for c in CAMPOS_ESPECTROS])
        for k in range(meta["n_bins"]):
            writer.writerow([k * fs / meta["nfft"]] +
                            [float(v) if np.isfinite(v) else "" for v in espectros[:, k]])
    with (carpeta / "metricas.csv").open("w", newline="", encoding="utf-8") as archivo:
        writer = csv.writer(archivo)
        writer.writerow(["metodo", "mse_codigo_adc2", "snr_db", "delta_snr_db", "energia_util_pct", "recortes_pwm"])
        writer.writerows(filas_metricas(meta))


def intervalos_invalidos(valida):
    cambios = np.diff(np.r_[False, ~valida, False].astype(int))
    return list(zip(np.flatnonzero(cambios == 1), np.flatnonzero(cambios == -1)))


def inicio_detalle(valida, muestras_detalle):
    # Selección de vista: primer tramo continuo con referencia para el zoom temporal.
    cambios = np.diff(np.r_[False, valida, False].astype(int))
    for inicio, fin in zip(np.flatnonzero(cambios == 1), np.flatnonzero(cambios == -1)):
        if fin - inicio >= muestras_detalle:
            return int(inicio)
    return 0


def guardar_figura(fig, carpeta, nombre):
    for extension in ("png", "pdf"):
        fig.savefig(carpeta / f"{nombre}.{extension}", dpi=180, facecolor="white")
    plt.close(fig)


def graficar(carpeta, meta, muestras, espectros, prueba, repeticion, inicio_ms, detalle_ms):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fs = meta["fs_hz"]
    tiempo = np.arange(len(muestras)) / fs
    valida = muestras[:, 3] != -32768
    limpia = muestras[:, 3].astype(float)
    limpia[~valida] = np.nan
    indices = {nombre: i for i, nombre in enumerate(CAMPOS_MUESTRAS)}
    n_detalle = max(2, round(detalle_ms * fs / 1000))
    inicio = inicio_detalle(valida, n_detalle) if inicio_ms is None else round(inicio_ms * fs / 1000)
    if not 0 <= inicio < len(muestras):
        raise ValueError("El inicio del detalle queda fuera de la captura.")
    fin = min(len(muestras), inicio + n_detalle)
    if fin - inicio < 2:
        raise ValueError("El detalle temporal requiere al menos dos muestras.")
    titulo = f"{prueba} · repetición {repeticion} · captura {meta['capture_id']}"
    fig, ejes = plt.subplots(3, 2, figsize=(12, 8), sharex="col", sharey=True)
    fig.subplots_adjust(top=.86, bottom=.16, left=.08, right=.98, hspace=.3, wspace=.18)
    fig.suptitle(titulo + "\nComparación temporal", fontsize=15, y=.975)
    for fila, clave in enumerate(("mezcla", "fir", "fft")):
        for col, tramo in enumerate((slice(None), slice(inicio, fin))):
            ax = ejes[fila, col]
            factor = 1 if col == 0 else 1000
            ax.plot(tiempo[tramo] * factor, muestras[tramo, indices[clave]],
                    color=COLORES[clave], linewidth=.75, label=NOMBRES[clave])
            ax.plot(tiempo[tramo] * factor, limpia[tramo], color=COLORES["referencia"],
                    linewidth=.8, alpha=.85, label="Referencia limpia")
            for a, b in intervalos_invalidos(valida):
                ax.axvspan(a / fs * factor, b / fs * factor, color="#F2CC8F", alpha=.4, zorder=0)
            if col == 0:
                ax.set_xlim(0, len(muestras) / fs)
                ax.set_ylabel("Códigos ADC")
            else:
                ax.set_xlim(tiempo[inicio] * factor, tiempo[fin - 1] * factor)
            ax.grid(alpha=.2)
            ax.legend(loc="upper right", fontsize=8, framealpha=.9)
    ejes[0, 0].set_title("Captura completa")
    ejes[0, 1].set_title("Detalle temporal")
    ejes[2, 0].set_xlabel("Tiempo (s)")
    ejes[2, 1].set_xlabel("Tiempo (ms)")
    fig.text(.08, .035, f"Referencia válida en {meta['reference_pct']:.1f}% de las muestras. "
             "Fondo ámbar = referencia ausente.\n"
             f"FIR alineado por el S3 ({meta['fir_delay_compensated_samples']} muestras compensadas). "
             "Escala de amplitud común.", fontsize=9)
    guardar_figura(fig, carpeta, "senales_tiempo")

    fig = plt.figure(figsize=(12, 8))
    rejilla = fig.add_gridspec(2, 1, height_ratios=[3.4, 1], left=.09, right=.98,
                             top=.88, bottom=.13, hspace=.32)
    ax = fig.add_subplot(rejilla[0])
    frecuencia = np.arange(meta["n_bins"]) * fs / meta["nfft"]
    for canal, clave in enumerate(CAMPOS_ESPECTROS):
        if np.isfinite(espectros[canal]).any():
            ax.plot(frecuencia, espectros[canal], color=COLORES[clave],
                    linewidth=1.1, label=NOMBRES[clave])
    ax.set_xlabel("Frecuencia (Hz)")
    ax.set_ylabel("Densidad espectral (dB re 1 código ADC²/Hz)")
    ax.set_xlim(0, fs / 2)
    ax.grid(alpha=.2)
    if meta["spectrum_frames"]:
        ax.legend(loc="best", ncols=2)
    else:
        ax.text(.5, .5, "Captura menor que 1024 muestras: espectro no disponible",
                ha="center", transform=ax.transAxes)
    ax_tabla = fig.add_subplot(rejilla[1])
    ax_tabla.axis("off")
    filas = [[fila[0]] + [texto_numero(v) for v in fila[1:]] for fila in filas_metricas(meta)]
    tabla = ax_tabla.table(cellText=filas, colLabels=["Método", "MSE (cód.²)", "SNR (dB)",
                           "ΔSNR (dB)", "E útil (%)", "Recortes PWM"], loc="center")
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(10)
    tabla.scale(1, 1.65)
    for (fila, col), celda in tabla.get_celld().items():
        celda.set_edgecolor("#DDE2E6")
        if fila == 0:
            celda.set_facecolor("#E8F1F3")
            celda.set_text_props(weight="bold")
    soporte = ("ventanas completas con referencia, comunes a las cuatro señales"
               if meta["spectrum_scope"] == "referencia_comun"
               else "ventanas de la captura; referencia espectral no disponible")
    fig.suptitle(titulo + "\nEspectros y métricas calculados en el ESP32-S3", fontsize=15, y=.975)
    fig.text(.09, .045, f"Welch: Hann de {meta['nfft']} muestras, salto {meta['hop']}, "
             f"{meta['spectrum_frames']} ventanas.\nSoporte espectral: {soporte}.\n"
             f"MSE/SNR: {meta['reference_samples']} muestras con referencia. "
             f"Energía útil: {meta['energy_samples']} muestras con contexto completo.", fontsize=9)
    guardar_figura(fig, carpeta, "espectros_metricas")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", help="Puerto USB-UART del S3, por ejemplo COM5")
    parser.add_argument("--puertos", action="store_true", help="Listar puertos disponibles")
    parser.add_argument("--archivo", type=Path, help="Regenerar figuras de una captura.s3bin guardada")
    parser.add_argument("--prueba", choices=[f"P{i}" for i in range(1, 7)])
    parser.add_argument("--repeticion", type=int, default=1)
    parser.add_argument("--salida", type=Path, default=Path("resultados"))
    parser.add_argument("--descargar-existente", action="store_true")
    parser.add_argument("--inicio-ms", type=float)
    parser.add_argument("--detalle-ms", type=float, default=20)
    args = parser.parse_args()
    if args.puertos:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(f"{p.device}  {p.description}")
        return
    if bool(args.puerto) == bool(args.archivo) or not args.prueba:
        parser.error("Indicá --prueba y exactamente uno de --puerto o --archivo.")
    if args.repeticion < 1 or not np.isfinite(args.detalle_ms) or args.detalle_ms <= 0:
        parser.error("La repetición y la duración del detalle deben ser positivas.")
    if args.inicio_ms is not None and (not np.isfinite(args.inicio_ms) or args.inicio_ms < 0):
        parser.error("El inicio del detalle debe ser finito y no negativo.")
    if args.archivo:
        datos = recibir(io.BytesIO(args.archivo.read_bytes()))
    else:
        datos = adquirir(args)
    meta, muestras, espectros, bruto = datos
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    carpeta = args.salida / f"{args.prueba}_rep{args.repeticion}_{fecha}"
    carpeta.mkdir(parents=True, exist_ok=False)
    (carpeta / "captura.s3bin").write_bytes(bruto)
    envoltura = {"prueba_declarada": args.prueba, "repeticion": args.repeticion,
                 "nota": "Etiqueta asignada por el operador; verificar el emisor.", "s3": meta}
    (carpeta / "metadatos.json").write_text(json.dumps(envoltura, ensure_ascii=False, indent=2), encoding="utf-8")
    guardar_tablas(carpeta, meta, muestras, espectros)
    graficar(carpeta, meta, muestras, espectros, args.prueba, args.repeticion, args.inicio_ms, args.detalle_ms)
    print(f"Guardado en {carpeta.resolve()}")
    print(f"Referencia válida: {meta['reference_pct']:.1f}%. Final de captura: {meta['finish']}.")
    for fila in filas_metricas(meta):
        print(f"{fila[0]}: MSE {texto_numero(fila[1])}, SNR {texto_numero(fila[2])} dB")
    if any(meta["counters_delta"].values()):
        print("La captura registra incidencias de recepción:", meta["counters_delta"])
    if meta["reference_samples"] == 0:
        print("Esta toma carece de referencia válida. Repetí ref capturar 8 y luego la grabación.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido. Si estaba descargando, esperá a que el S3 vuelva a LISTA.", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, TimeoutError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
