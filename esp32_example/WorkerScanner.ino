// WorkerScanner.ino — ESP32 sample
// Posts token scans to Flask /api/scan and renders a small TFT status
// Libraries: WiFi.h, HTTPClient.h, Adafruit_GFX, Adafruit_ST7735 (or ILI9341)

#include <WiFi.h>
#include <HTTPClient.h>
// #include <Adafruit_GFX.h>
// #include <Adafruit_ST7735.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
String BASE_URL = "http://YOUR_SERVER_HOST"; // e.g., http://192.168.1.20:5000

// Adafruit_ST7735 tft = Adafruit_ST7735(/* CS=5, DC=2, RST=4 */);

void drawStatus(const String& line1, const String& line2, const String& line3){
  // tft.fillScreen(ST77XX_BLACK);
  // tft.setCursor(4, 10); tft.setTextColor(ST77XX_WHITE); tft.setTextSize(1);
  // tft.println(line1); tft.println(line2); tft.println(line3);
  Serial.println(line1 + " | " + line2 + " | " + line3);
}

void setup(){
  Serial.begin(115200);
  // tft.initR(INITR_BLACKTAB); tft.setRotation(1);
  drawStatus("Booting...", "", "");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  drawStatus("WiFi OK", WiFi.localIP().toString(), "");
}

void loop(){
  // Simulate a token scan every 5s
  static unsigned long last = 0;
  if (millis() - last > 5000) {
    last = millis();
    String token = "1001"; // replace with real scan payload
    HTTPClient http;
    http.begin(BASE_URL + "/api/scan");
    http.addHeader("Content-Type", "application/json");
    String body = String("{"token_id":"") + token + "","scanner_id":"S1"}";
    int code = http.POST(body);
    if (code > 0) {
      String res = http.getString();
      drawStatus("POST /api/scan", "HTTP " + String(code), "");
      Serial.println(res);
    } else {
      drawStatus("HTTP error", String(code), "");
    }
    http.end();
  }
}
