// ============================================================================
// SISNAM 2.0 - Sistem Monitoring & Kontrol Kamar Mandi Pintar (ESP32)
// Sensor Kehadiran Radar mmWave HLK-LD2410C (GPIO 22) + Relay Lampu (GPIO 23)
// Kelompok 8 - Mendukung Endpoint /status & /control?mode=AUTO|ON|OFF
// ============================================================================

#include <WiFi.h>
#include <WebServer.h>

// --- KONFIGURASI WIFI ---
const char* ssid = "vanity";
const char* pass = "gatauluoa";

// --- KONFIGURASI PIN ---
const int sensorPin = 22; // Pin OUT dari HLK-LD2410C ke GPIO 22
const int relayPin  = 23; // Pin IN Relay Lampu (Silakan ubah sesuai rangkaian Anda)

// Konfigurasi Tipe Relay (Kebanyakan modul relay di pasaran aktif saat diberi logika LOW)
// Ubah menjadi HIGH jika relay Anda aktif saat diberi logika HIGH
const int RELAY_ON  = LOW;
const int RELAY_OFF = HIGH;

// --- VARIABEL STATUS SISTEM ---
// Mode: 0 = AUTO (Ikut Sensor), 1 = MANUAL ON (Paksa Nyala), 2 = MANUAL OFF (Paksa Mati)
int systemMode = 0; 
bool adaOrang = false;
bool lampuMenyala = false;

WebServer server(80);

// Fungsi untuk menyinkronkan kondisi Relay berdasarkan Mode & Sensor
void updateRelayState() {
  if (systemMode == 0) {
    // Mode Otomatis: Mengikuti pembacaan sensor radar HLK-LD2410C
    lampuMenyala = adaOrang;
  } else if (systemMode == 1) {
    // Mode Paksa ON
    lampuMenyala = true;
  } else if (systemMode == 2) {
    // Mode Paksa OFF
    lampuMenyala = false;
  }

  digitalWrite(relayPin, lampuMenyala ? RELAY_ON : RELAY_OFF);
}

// Endpoint GET /status -> Mengirim data ke Aplikasi Python / Web dalam format JSON
void handleStatus() {
  String modeStr = "AUTO";
  if (systemMode == 1) modeStr = "MANUAL_ON";
  else if (systemMode == 2) modeStr = "MANUAL_OFF";

  String json = "{";
  json += "\"presence\":" + String(adaOrang ? "true" : "false") + ",";
  json += "\"lamp\":" + String(lampuMenyala ? "true" : "false") + ",";
  json += "\"mode\":\"" + modeStr + "\",";
  json += "\"rssi\":" + String(WiFi.RSSI()) + ",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\"";
  json += "}";

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// Endpoint GET /control?mode=... -> Menerima perintah dari tombol Aplikasi Python / Web
void handleControl() {
  if (server.hasArg("mode")) {
    String reqMode = server.arg("mode");
    if (reqMode == "AUTO") {
      systemMode = 0;
      Serial.println("Mode diubah ke: OTOMATIS (Sensor)");
    } else if (reqMode == "ON") {
      systemMode = 1;
      Serial.println("Mode diubah ke: MANUAL ON (Paksa Nyala)");
    } else if (reqMode == "OFF") {
      systemMode = 2;
      Serial.println("Mode diubah ke: MANUAL OFF (Paksa Mati)");
    }
    updateRelayState();
    handleStatus(); // Kembalikan status terbaru
  } else {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "text/plain", "Parameter 'mode' diperlukan");
  }
}

void setup() {
  Serial.begin(115200);

  // Pin sensor menggunakan INPUT_PULLDOWN agar tidak floating
  pinMode(sensorPin, INPUT_PULLDOWN);
  
  // Set pin relay sebagai OUTPUT dan matikan di awal
  pinMode(relayPin, OUTPUT);
  digitalWrite(relayPin, RELAY_OFF);

  Serial.println("\nMenghubungkan ke WiFi: " + String(ssid));
  WiFi.begin(ssid, pass);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nBerhasil terhubung ke WiFi!");
  Serial.print("IP Address ESP32 (Masukkan ke Aplikasi Web): ");
  Serial.println(WiFi.localIP());

  // Daftarkan rute Web Server
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/control", HTTP_GET, handleControl);
  server.begin();
  Serial.println("HTTP Server Lokal Aktif!");
}

void loop() {
  server.handleClient();

  // Baca output digital dari pin OUT sensor HLK-LD2410C
  int bacaSensor = digitalRead(sensorPin);
  bool statusSekarang = (bacaSensor == HIGH);

  // Jika terjadi perubahan deteksi keberadaan
  if (statusSekarang != adaOrang) {
    adaOrang = statusSekarang;
    if (adaOrang) {
      Serial.println("Sensor Radar -> Ada Orang!");
    } else {
      Serial.println("Sensor Radar -> Ruangan Kosong");
    }
  }

  // Terapkan logika ke relay
  updateRelayState();
  delay(20);
}
