// Generado por main.py + convert_oled.py - no editar a mano
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <LittleFS.h>

#define SDA_PIN   8
#define SCL_PIN   9
#define OLED_ADDR 0x3C
#define OLED_W    128
#define OLED_H    64
#define FB_PATH   "/badapple.bin"

const unsigned long FRAME_MS = 33;
const int NF = 6572;
const int VW = 85;
const int VH = 64;
const int BK = 1;
const int OX = 21;
const int OY = 0;
const int FB = 704;

Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);
uint8_t frameBuf[FB];
File vfile;

void drawFrame(const uint8_t *bits) {
  for (int y = 0; y < VH; y++) {
    for (int x = 0; x < VW; x++) {
      if (bits[y * ((VW + 7) / 8) + x / 8] & (0x80 >> (x % 8)))
        display.fillRect(OX + x * BK, OY + y * BK, BK, BK, SSD1306_WHITE);
    }
  }
}

bool readFrame(size_t i) {
  if (!vfile.seek((uint32_t)i * FB)) return false;
  size_t got = 0;
  while (got < FB) {
    int r = vfile.read(frameBuf + got, FB - got);
    if (r <= 0) return false;
    got += (size_t)r;
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("OLED SSD1306 no encontrado (I2C: SDA 8, SCL 9, 0x3C)"));
    for (;;);
  }
  Serial.println(F("OLED OK"));
  if (!LittleFS.begin(true)) {
    Serial.println(F("ERROR: no se pudo montar LittleFS"));
    for (;;);
  }
  vfile = LittleFS.open(FB_PATH, "r");
  if (!vfile) {
    Serial.println(F("ERROR: falta /badapple.bin en LittleFS (corre main.py)"));
    for (;;);
  }
  Serial.printf("LittleFS OK: %s = %u bytes (esperado %u, %d frames)\n",
                FB_PATH, (unsigned)vfile.size(), (unsigned)((uint32_t)NF * FB), NF);
  display.clearDisplay();
}

void loop() {
  unsigned long t = millis() % ((unsigned long)NF * FRAME_MS);
  size_t i = t / FRAME_MS;
  if (readFrame(i)) {
    display.clearDisplay();
    drawFrame(frameBuf);
    display.display();
  }
}
