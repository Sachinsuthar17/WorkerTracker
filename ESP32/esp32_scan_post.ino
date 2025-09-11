// ESP32 QR scanner sketch for posting worker and bundle scans to the Flask server.
//
// Hardware assumptions:
// - A serial-based QR scanner is connected to Serial2 (GPIO16 RX2, GPIO17 TX2) at 9600 baud.
// - A small TFT or OLED display (TFT_eSPI) is configured via User_Setup.h and wired up
//   appropriately.  This display is used to prompt the operator and show the result of
//   each scan/post.
// - The board connects to WiFi using the credentials defined below.
//
// Software assumptions:
// - The server accepts POST requests to /scan with JSON containing token_id,
//   bundle_id, and operation_id.  A successful response returns HTTP 200 with a JSON
//   body; an error response will set an error status code.

#include <WiFi.h>
#include <HTTPClient.h>
#include <TFT_eSPI.h>

// Replace these with your WiFi credentials
#define WIFI_SSID "YOUR_SSID"
#define WIFI_PASS "YOUR_PASSWORD"

// Address of your Flask server (e.g. http://192.168.1.100:5000/scan)
#define SERVER_URL "http://your-server-host/scan"

TFT_eSPI tft = TFT_eSPI();
String workerToken = "";
String bundleId = "";
int operationId = 5077; // Example operation sequence (configure as needed)

// Display a message on the TFT
void showMsg(const String &line1, const String &line2 = "") {
  tft.fillScreen(TFT_BLACK);
  tft.setCursor(4, 10);
  tft.setTextSize(2);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.println(line1);
  if (line2.length()) {
    tft.setCursor(4, 40);
    tft.println(line2);
  }
}

// Read a scan from Serial2, waiting up to 8 seconds.  Returns empty string on timeout.
String readScan() {
  String s = "";
  unsigned long timeout = millis() + 8000;
  while (millis() < timeout) {
    while (Serial2.available()) {
      char c = Serial2.read();
      if (c == '\n' || c == '\r') {
        if (s.length() > 0) return s;
      } else {
        s += c;
      }
    }
    delay(5);
  }
  return "";
}

void setup() {
  Serial.begin(115200);
  Serial2.begin(9600);
  tft.init();
  tft.setRotation(1);
  showMsg("Connecting WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  showMsg("WiFi OK", WiFi.localIP().toString());
}

void loop() {
  showMsg("Scan Worker QR");
  workerToken = readScan();
  if (workerToken.length() == 0) return;

  showMsg("Scan Bundle QR");
  bundleId = readScan();
  if (bundleId.length() == 0) return;

  // Construct JSON payload manually (simple concatenation)
  String payload = String("{\"token_id\":\"") + workerToken + "\",\"bundle_id\":\"" + bundleId + "\",\"operation_id\":\"" + String(operationId) + "\"}";
  Serial.println(payload);

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(payload);
    String resp = http.getString();
    http.end();

    if (code == 200) {
      showMsg("Scan OK", resp);
    } else {
      showMsg("Scan Failed", String(code));
    }
  } else {
    showMsg("No WiFi");
  }

  delay(1500);
}