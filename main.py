# -*- coding: utf-8 -*-
"""
main.py
=======

Script de un solo paso para el proyecto "Bad Apple en OLED ESP32-S3".

Modo 1 (frames propios): convierte los frames de ``pngs/`` a
``data/badapple.bin`` llamando a ``convert_oled.py`` (allí se configuran
FPS, umbral blanco/negro, etc.) y regenera ``data/video_meta.json``.

Modo 2 (sin pngs): si no hay ``pngs/`` usa el binario y el metadato que ya
vienen incluidos en el repositorio (``data/badapple.bin`` +
``data/video_meta.json``). Así cualquiera puede reproducir sin instalar
pygame ni extraer frames con ffmpeg.

En ambos casos genera ``src/main.cpp``, compila y sube con PlatformIO
(``pio``): primero el filesystem (LittleFS) y luego la app, con un UNICO
reset de la placa al final.

Uso::

    python main.py               convertir/usar binario + subir FS + subir app
    python main.py --no-fs       convertir/usar binario + compilar, subir solo la app
    python main.py --no-upload   compilar sin subir nada

El binario del video NO se compila dentro del firmware: se guarda en la
particion de datos, por eso caben todos los frames a resolucion completa.
"""

import subprocess, sys, os, glob, shutil, json

# ---------------------------------------------------------------------------
# Opciones de linea de comandos
# ---------------------------------------------------------------------------
NO_UPLOAD = '--no-upload' in sys.argv
NO_FS = '--no-fs' in sys.argv or NO_UPLOAD


def load_video_params():
    """Obtiene los parametros del video en (cantidad_pngs, dict).

    - Si hay frames en ``pngs/`` los convierte a ``data/badapple.bin`` y
      refresca ``data/video_meta.json`` (require pygame).
    - Si NO hay frames pero existen ``data/badapple.bin`` + ``data/video_meta.json``
      (ambos versionados en el repo), los usa tal cual: permite reproducir SIN
      instalar pygame ni generar frames con ffmpeg.
    """
    n = len(glob.glob('pngs/*.png'))
    if n:
        from convert_oled import NF, FPS, VW, VH, BK, OX, OY, FB, SCR_W, SCR_H
        return n, dict(NF=NF, FPS=FPS, VW=VW, VH=VH, BK=BK, OX=OX, OY=OY,
                       FB=FB, SCR_W=SCR_W, SCR_H=SCR_H)
    if os.path.isfile('data/badapple.bin') and os.path.isfile('data/video_meta.json'):
        with open('data/video_meta.json') as f:
            return 0, json.load(f)
    print('ERROR: no hay pngs/ para convertir, y tampoco data/badapple.bin'
          ' + data/video_meta.json.\nExtrae los frames con ffmpeg (ver README)'
          ' o restaura el binario desde el repositorio.')
    sys.exit(1)


n_pngs, meta = load_video_params()
if n_pngs:
    print(f'Loaded {n_pngs} images (convirtiendo a data/badapple.bin)\n')
else:
    print('Sin pngs/: usando data/badapple.bin existente (video_meta.json)\n')

# Parametros del video: NF, FPS, VW, VH, BK (tamano de bloque), OX/OY (offset
# centrado), FB (bytes por frame) y SCR_W/SCR_H (tamano del panel). Vienen de
# la conversion recien hecha o de data/video_meta.json cuando no hay pngs/.
NF = int(meta['NF']); FPS = int(meta['FPS'])
VW = int(meta['VW']); VH = int(meta['VH']); BK = int(meta['BK'])
OX = int(meta['OX']); OY = int(meta['OY']); FB = int(meta['FB'])
SCR_W = int(meta['SCR_W']); SCR_H = int(meta['SCR_H'])

print('Creating src/main.cpp...\n')

os.makedirs('src', exist_ok=True)

# Duracion de cada frame en milisegundos (reloj del bucle de reproduccion).
FRAME_MS = round(1000 / FPS)

# ---------------------------------------------------------------------------
# Generacion del firmware (src/main.cpp)
# ---------------------------------------------------------------------------
# El C++ se genera con los valores reales del video para no recalcular nada
# en la placa. El firmware abre /badapple.bin desde LittleFS y en cada tick
# lee el frame correspondiente usando un reloj de millis(): si el panel tarda,
# se saltan frames en lugar de atrasarse la reproduccion.
main_cpp = f"""// Generado por main.py + convert_oled.py - no editar a mano
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <LittleFS.h>

#define SDA_PIN   8
#define SCL_PIN   9
#define OLED_ADDR 0x3C
#define OLED_W    {SCR_W}
#define OLED_H    {SCR_H}
#define FB_PATH   "/badapple.bin"

const unsigned long FRAME_MS = {FRAME_MS};
const int NF = {NF};
const int VW = {VW};
const int VH = {VH};
const int BK = {BK};
const int OX = {OX};
const int OY = {OY};
const int FB = {FB};

Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);
uint8_t frameBuf[FB];
File vfile;

void drawFrame(const uint8_t *bits) {{
  for (int y = 0; y < VH; y++) {{
    for (int x = 0; x < VW; x++) {{
      if (bits[y * ((VW + 7) / 8) + x / 8] & (0x80 >> (x % 8)))
        display.fillRect(OX + x * BK, OY + y * BK, BK, BK, SSD1306_WHITE);
    }}
  }}
}}

bool readFrame(size_t i) {{
  if (!vfile.seek((uint32_t)i * FB)) return false;
  size_t got = 0;
  while (got < FB) {{
    int r = vfile.read(frameBuf + got, FB - got);
    if (r <= 0) return false;
    got += (size_t)r;
  }}
  return true;
}}

void setup() {{
  Serial.begin(115200);
  delay(300);
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {{
    Serial.println(F("OLED SSD1306 no encontrado (I2C: SDA 8, SCL 9, 0x3C)"));
    for (;;);
  }}
  Serial.println(F("OLED OK"));
  if (!LittleFS.begin(true)) {{
    Serial.println(F("ERROR: no se pudo montar LittleFS"));
    for (;;);
  }}
  vfile = LittleFS.open(FB_PATH, "r");
  if (!vfile) {{
    Serial.println(F("ERROR: falta /badapple.bin en LittleFS (corre main.py)"));
    for (;;);
  }}
  Serial.printf("LittleFS OK: %s = %u bytes (esperado %u, %d frames)\\n",
                FB_PATH, (unsigned)vfile.size(), (unsigned)((uint32_t)NF * FB), NF);
  display.clearDisplay();
}}

void loop() {{
  unsigned long t = millis() % ((unsigned long)NF * FRAME_MS);
  size_t i = t / FRAME_MS;
  if (readFrame(i)) {{
    display.clearDisplay();
    drawFrame(frameBuf);
    display.display();
  }}
}}
"""

with open('src/main.cpp', 'w') as f:
    f.write(main_cpp)

print(f"Done ({NF} frames, {FB} bytes/frame, {round(NF * FB / 1e6, 2)} MB en FS)\n")

if NO_UPLOAD:
    print("(sin subir: --no-upload)")
    sys.exit(0)


def detect_port():
    """Detecta el puerto serial del ESP32-S3 via `pio device list`.

    Busca un puerto cuyo Hardware ID contenga 0x303A (VID de Espressif / USB
    nativo del ESP32-S3). Devuelve el nombre del puerto o None.
    """
    pio = shutil.which('pio') or r'C:\Users\josea\.platformio\penv\Scripts\pio.exe'
    try:
        out = subprocess.run([pio, 'device', 'list'], capture_output=True, text=True, timeout=30)
        lines = out.stdout.splitlines()
        cand = None
        for ln in lines:
            t = ln.strip()
            if not t:
                continue
            if t == '----':
                pass
            elif t.endswith('----') or (cand is None and ':' not in t and not t.startswith('USB')):
                cand = t
            elif 'Hardware ID' in t and '303A' in t and cand:
                return cand
    except Exception:
        pass
    return None


def hard_reset(port):
    """Reinicia la placa UNA sola vez al final.

    Con ``board_upload.after_reset = no_reset`` (platformio.ini) ninguno de los
    dos uploads reinicia el chip. Aqui se hace el unico reset, con el esptool
    que viene incluido en PlatformIO, para que arranque la app ya flasheada.
    """
    py = os.path.join(os.path.expanduser('~'), '.platformio', 'penv', 'Scripts', 'python.exe')
    esptool = os.path.join(os.path.expanduser('~'), '.platformio', 'packages', 'tool-esptoolpy', 'esptool.py')
    if not os.path.isfile(py) or not os.path.isfile(esptool):
        return False
    subprocess.run([py, esptool, '--chip', 'esp32s3', '--port', port,
                    '--before', 'default_reset', '--after', 'hard_reset', 'read_mac'],
                   check=False)
    return True


# ---------------------------------------------------------------------------
# Flujo principal: detectar placa, subir filesystem y app, reset final
# ---------------------------------------------------------------------------
port = detect_port()
if port:
    os.environ['PLATFORMIO_UPLOAD_PORT'] = port
    print(f'Placa detectada en {port}\n')

pio = shutil.which('pio')
if not pio:
    pio = r'C:\Users\josea\.platformio\penv\Scripts\pio.exe'
    if not os.path.isfile(pio):
        print('No encuentro pio en el PATH ni en ~/.platformio/penv/Scripts.')
        sys.exit(1)

run = lambda *args: subprocess.run([pio, 'run', *args], check=True)

if not NO_FS:
    run('-t', 'uploadfs')          # 1) sube data/badapple.bin a LittleFS
else:
    run()                          # solo compila (el FS ya esta en la placa)

run('-t', 'upload')                # 2) compila y sube la app

if not port:
    port = detect_port()

if port and hard_reset(port):
    print('\nOK: filesystem + app subidos (un solo reset al final)')
else:
    print('\nOK: subido. Pulsa RESET en la placa para arrancar la app.')