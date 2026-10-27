import http.server
import socketserver
import urllib.request
from urllib.parse import urlparse
import json
import os
import threading
import time
import copy

PORT = 8080
HTML_FILE = "sisnam.html"
ROOMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rooms.json")

lock = threading.Lock()
rooms = []  # State sentral: [{id, name, ip, source, presence, lamp, mode, rssi, online, stateSince, detections}]


def load_rooms():
    global rooms
    if os.path.exists(ROOMS_FILE):
        try:
            with open(ROOMS_FILE, "r", encoding="utf-8") as f:
                rooms = json.load(f)
                # Reset online status saat restart server
                for r in rooms:
                    r["online"] = False
        except Exception:
            rooms = []


def save_rooms():
    with open(ROOMS_FILE, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=2)


def norm_mode(m):
    if m in ("MANUAL_ON", "ON"):
        return "ON"
    if m in ("MANUAL_OFF", "OFF"):
        return "OFF"
    return "AUTO"


def poll_one(room):
    """Poll satu ESP32 dan update state room in-place."""
    if room.get("source") == "SIM":
        room["online"] = True
        return

    ip = room.get("ip", "").strip()
    if not ip:
        room["online"] = False
        return

    try:
        req = urllib.request.Request(f"http://{ip}/status")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            d = json.loads(resp.read())

        prev = room.get("presence", False)
        now = bool(d.get("presence", False))

        room["online"] = True
        room["presence"] = now
        room["lamp"] = bool(d.get("lamp", False))
        room["mode"] = norm_mode(d.get("mode", "AUTO"))
        room["rssi"] = d.get("rssi", None)

        if now != prev:
            room["stateSince"] = time.time() * 1000
            if now:
                room["detections"] = room.get("detections", 0) + 1
    except Exception:
        room["online"] = False


def poller_thread():
    """Background thread: polling semua ESP32 setiap 1 detik."""
    while True:
        with lock:
            snapshot = [dict(r) for r in rooms]

        for r in snapshot:
            poll_one(r)

        with lock:
            for updated in snapshot:
                for r in rooms:
                    if r["id"] == updated["id"]:
                        for k in ("presence", "lamp", "mode", "rssi", "online", "stateSince", "detections"):
                            if k in updated:
                                r[k] = updated[k]
                        break
            save_rooms()

        time.sleep(1)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self.path = "/" + HTML_FILE
            return super().do_GET()
        if p == "/state":
            with lock:
                d = copy.deepcopy(rooms)
            return self.json_ok(d)
        return super().do_GET()

    def do_POST(self):
        body = self._body()
        p = urlparse(self.path).path

        if p == "/rooms/add":
            r = {
                "id": f"room-{int(time.time() * 1000)}",
                "name": body.get("name", "Ruangan"),
                "ip": body.get("ip", ""),
                "source": body.get("source", "LIVE"),
                "presence": False, "lamp": False, "mode": "AUTO",
                "rssi": None, "online": False,
                "stateSince": time.time() * 1000, "detections": 0
            }
            with lock:
                rooms.append(r)
                save_rooms()
            return self.json_ok(r)

        if p == "/rooms/delete":
            with lock:
                rooms[:] = [r for r in rooms if r["id"] != body.get("id")]
                save_rooms()
            return self.json_ok({"ok": True})

        if p == "/rooms/edit":
            with lock:
                for r in rooms:
                    if r["id"] == body.get("id"):
                        if "name" in body:
                            r["name"] = body["name"]
                        if "ip" in body:
                            r["ip"] = body["ip"]
                        if "source" in body:
                            r["source"] = body["source"]
                save_rooms()
            return self.json_ok({"ok": True})

        if p == "/control":
            rid = body.get("id", "")
            mode = body.get("mode", "AUTO")
            with lock:
                room = next((r for r in rooms if r["id"] == rid), None)
            if not room:
                return self.json_err(404, "Room not found")

            if room.get("source") == "SIM":
                with lock:
                    m = norm_mode(mode)
                    room["mode"] = m
                    if m == "AUTO":
                        room["lamp"] = room["presence"]
                    elif m == "ON":
                        room["lamp"] = True
                    else:
                        room["lamp"] = False
                    save_rooms()
                return self.json_ok({"ok": True})

            ip = room.get("ip", "").strip()
            try:
                req = urllib.request.Request(f"http://{ip}/control?mode={mode}")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    d = json.loads(resp.read())
                with lock:
                    room["mode"] = norm_mode(d.get("mode", mode))
                    room["lamp"] = bool(d.get("lamp"))
                    room["presence"] = bool(d.get("presence"))
                    room["rssi"] = d.get("rssi")
                    room["online"] = True
                    save_rooms()
                return self.json_ok({"ok": True})
            except Exception as e:
                return self.json_err(502, str(e))

        if p == "/sim":
            rid = body.get("id", "")
            pres = bool(body.get("presence", False))
            with lock:
                room = next((r for r in rooms if r["id"] == rid), None)
                if room and room.get("source") == "SIM":
                    prev = room.get("presence", False)
                    room["presence"] = pres
                    if room["mode"] == "AUTO":
                        room["lamp"] = pres
                    if pres != prev:
                        room["stateSince"] = time.time() * 1000
                        if pres:
                            room["detections"] = room.get("detections", 0) + 1
                    save_rooms()
            return self.json_ok({"ok": True})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    def json_ok(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def json_err(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_rooms()

    threading.Thread(target=poller_thread, daemon=True).start()

    print(f"[✓] Server aktif di http://localhost:{PORT}")
    print(f"[✓] Background poller aktif — polling ESP32 setiap 1 detik")
    print(f"[✓] Data ruangan: {ROOMS_FILE}")
    print(f"[✓] Semua client (localhost, ngrok, HP) melihat state yang sama")

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with S(("0.0.0.0", PORT), Handler) as h:
        h.serve_forever()
