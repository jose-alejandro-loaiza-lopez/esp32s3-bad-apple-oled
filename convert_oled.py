# -*- coding: utf-8 -*-
"""
convert_oled.py
===============

Convierte los frames de la carpeta ``pngs/`` (cualquier resolucion y cualquier
video) a un archivo binario de 1 bit por pixel (1bpp) listo para Adafruit GFX +
SSD1306 (128x64) y lo escribe en ``data/badapple.bin``.

Ese binario es el que ``main.py`` sube a la particion LittleFS del ESP32-S3,
de modo que el video completo vive en la placa a resolucion completa sin
recortar la duracion.

Pipeline visual::

    video.mp4 --(ffmpeg)--> pngs/png (N).png --(este script)--> data/badapple.bin

Que hace con cada frame:
    - Lo encaja dentro de 128x64 conservando su RELACION DE ASPECTO
      (fit, nunca recorta ni deforma) y lo centra con bordes negros.
    - Binariza cada pixel a BLANCO/NEGRO usando ``BW_THRESHOLD``.
    - Empaqueta el frame como bits (MSB = pixel mas a la izquierda).

Modos de resolucion:
    - ``FULL_RES = True`` (por defecto): rejilla 1x1, resolucion completa.
      Como el video se guarda en la particion de datos (varios MB) y no en la
      app, caben TODOS los frames.
    - ``FULL_RES = False``: cada pixel se dibuja como bloques ``BK x BK``
      (resolucion menor, menos bytes por frame, tambien caben todos).

Formato del binario:
    Frames consecutivos de ``FB = ((VW + 7) // 8) * VH`` bytes cada uno.
    El frame ``i`` ocupa el rango ``[i*FB, (i+1)*FB)``. Un bit a 1 = blanco.

Ajustes tipicos (editar aqui):
    ``FPS``          -> velocidad de reproduccion y de lectura del video.
    ``BW_THRESHOLD`` -> umbral de binarizacion blanco/negro (0-255).
    ``FULL_RES``     -> resolucion completa (True) o bloques (False).
    ``FS_CAP``       -> tamano de la particion de datos (bytes).
    ``SCR_W/SCR_H``  -> resolucion del panel OLED.
"""

import pygame, glob, os, re

pygame.init()
pygame.display.set_mode((1, 1))

FPS = 30                               # fotogramas por segundo de tu video
SCR_W, SCR_H = 128, 64                 # resolucion del OLED (SSD1306)
FS_CAP = 0xBE0000                      # particion de datos custom: spiffs en
                                       # partitions_custom.csv, offset 0x410000,
                                       # tamano ~12.4 MB

FULL_RES = True                        # True = rejilla 1x1 a resolucion completa

# ---------------------------------------------------------------------------
# Umbral de binarizacion BLANCO/NEGRO (0-255)
# ---------------------------------------------------------------------------
# Un pixel se pinta BLANCO si sus canales R, G y B son TODOS mayores que este
# valor; si no, queda NEGRO. Cuanto MAS ALTO el umbral, MAS area negra (menos
# sensibilidad al ruido/grises); cuanto MAS BAJO, MAS area blanca.
#
#   255  -> solo el blanco puro pasa a blanco (muy estricto)
#   127  -> valor por defecto (bueno para videos en blanco y negro)
#   64   -> casi cualquier cosa clara cuenta como blanco
BW_THRESHOLD = 127


def is_white(color):
    """True si el pixel ``color`` (r, g, b, a) se considera BLANCO."""
    r, g, b, a = color
    return r > BW_THRESHOLD and g > BW_THRESHOLD and b > BW_THRESHOLD and a > 127


def fit_in(src_w, src_h, box_w, box_h):
    """Escala manteniendo la relacion de aspecto hasta caber en ``box_w x box_h``."""
    scale = min(box_w / src_w, box_h / src_h)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))


def choose_grid(tw, th, max_px):
    """Elige la rejilla BK x BK que quepa en la pantalla sin superar ``max_px`` pixeles."""
    for k in range(1, 17):
        vw = max(1, round(tw / k))
        vh = max(1, round(th / k))
        if vw * vh <= max_px:
            return k, vw, vh
    return 16, max(1, round(tw / 16)), max(1, round(th / 16))


def frame_bytes(img, vw, vh):
    """Convierte ``img`` a ``(vw x vh)`` y lo empaqueta como bits (1 = blanco)."""
    resized = pygame.transform.scale(img, (vw, vh))
    data = []
    for y in range(vh):
        for bx in range((vw + 7) // 8):
            v = 0
            for px in range(8):
                x = bx * 8 + px
                if x < vw and is_white(resized.get_at((x, y))):
                    v |= 1 << (7 - px)
            data.append(v)
    return bytes(data)


# Frames ordenados numericamente (ffmpeg genera png (1).png, (2).png, ...).
def frame_number(path):
    m = re.search(r'(\d+)', os.path.basename(path))
    return int(m.group(1)) if m else 0


paths = sorted(glob.glob('pngs/*.png'), key=frame_number)
if not paths:
    print('No hay PNGs en pngs/ (usa ffmpeg para extraerlos).')
    raise SystemExit(1)

# Aspecto uniforme de video: lo tomo del primer frame (mismo archivo fuente).
first = pygame.image.load(paths[0]).convert_alpha()
src_w, src_h = first.get_size()

tw, th = fit_in(src_w, src_h, SCR_W, SCR_H)
if FULL_RES:
    VW, VH, BK = tw, th, 1
else:
    BK, VW, VH = choose_grid(tw, th, 3072)

OX = (SCR_W - VW * BK) // 2
OY = (SCR_H - VH * BK) // 2
FB = ((VW + 7) // 8) * VH

max_frames = FS_CAP // FB

os.makedirs('data', exist_ok=True)
out_path = os.path.join('data', 'badapple.bin')
NF = 0
with open(out_path, 'wb') as out:
    for p in paths:
        img = pygame.image.load(p).convert_alpha()
        out.write(frame_bytes(img, VW, VH))
        NF += 1
        if NF >= max_frames:
            break

total_bytes = NF * FB
if NF < len(paths):
    print(f'AVISO: {len(paths)} frames no caben en la particion'
          f' ({total_bytes} > {FS_CAP} bytes); se usan los primeros {NF}.')

print(f'Fuente {src_w}x{src_h} -> contenido {tw}x{th} -> rejilla {VW}x{VH} '
      f'(bloque {BK}x{BK}, offset {OX},{OY}, {FB} bytes/frame)')
print(f'Listo: {NF} frames, total {total_bytes} bytes ({round(total_bytes / 1e6, 2)} MB) '
      f'-> {out_path} ({round(NF / FPS)}s de video).')