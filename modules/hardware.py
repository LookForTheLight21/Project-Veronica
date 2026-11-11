"""
Tier 1 Pod Receiver & Hardware Abstraction for Project Veronica.
Raspberry Pi 5 receives events wirelessly from the ESP32 Teacher Lectern Pod
via TCP/UDP JSON packets on port 8765.
"""
import time
import json
import socket
import select
import threading

import state
from config import POD_SERVER_HOST, POD_SERVER_PORT, NFC_MAP


class BuzzerController:
    """
    Sends acoustic feedback commands to the ESP32 Lectern Pod,
    or sounds a local/console alert if pod is unreachable.
    """
    def __init__(self, pod_server=None):
        self.pod_server = pod_server

    def beep(self, times=1, duration=0.15, gap=0.08, freq=None):
        # Convert seconds to ms for microcontroller
        duration_ms = int(duration * 1000)
        gap_ms = int(gap * 1000)
        import config
        actual_freq = int(freq or getattr(config, "BUZZER_FREQ", 2000))
        if self.pod_server:
            self.pod_server.send_to_pod({
                "cmd": "beep",
                "times": times,
                "duration": duration_ms,
                "gap": gap_ms,
                "freq": actual_freq
            })
        print(f"🔊 [Acoustic Tone]: {times} beep(s) @ {actual_freq}Hz")


class PodReceiverServer:
    """
    Wireless link receiver for the Tier 1 ESP32 Lectern Pod.
    Accepts incoming TCP/UDP connections, parses JSON telemetry,
    and dispatches keypresses and NFC card events in real time (<10ms).
    """
    def __init__(self, host=POD_SERVER_HOST, port=POD_SERVER_PORT, on_key=None, on_nfc=None):
        self.host = host
        self.port = port
        self.on_key = on_key
        self.on_nfc = on_nfc
        self.running = False
        self.active_client_sock = None
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._server_loop, daemon=True)
        thread.start()
        print(f"📡 Pod Receiver listening on {self.host}:{self.port} (Wireless Link Ready)")

    def send_to_pod(self, payload):
        """Sends control JSON commands (e.g. buzzer beep) to connected ESP32 pod."""
        with self._lock:
            if self.active_client_sock:
                try:
                    data = (json.dumps(payload) + "\n").encode("utf-8")
                    self.active_client_sock.sendall(data)
                except Exception as e:
                    print(f"⚠️  Failed to send command to Pod: {e}")
                    self.active_client_sock = None
                    state.pod_connected = False

    def _server_loop(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind((self.host, self.port))
            server_sock.listen(2)
        except Exception as e:
            print(f"❌ Failed to bind Pod receiver server: {e}")
            return

        while self.running:
            try:
                client_sock, addr = server_sock.accept()
                with self._lock:
                    self.active_client_sock = client_sock
                    state.pod_connected = True
                    state.pod_last_seen = time.time()
                    state.pod_ip = addr[0]

                print(f"🟢 Lectern Pod Connected from {addr[0]}:{addr[1]}")
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    print(f"⚠️  Pod receiver accept error: {e}")
                time.sleep(1)

    def _handle_client(self, client_sock, addr):
        buffer = ""
        client_sock.settimeout(5.0)

        while self.running:
            try:
                chunk = client_sock.recv(1024).decode("utf-8")
                if not chunk:
                    break
                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    self._dispatch_message(line)
                    state.pod_last_seen = time.time()

            except socket.timeout:
                # Check link freshness
                if time.time() - state.pod_last_seen > 12.0:
                    state.pod_connected = False
                continue
            except Exception as e:
                break

        with self._lock:
            if self.active_client_sock == client_sock:
                self.active_client_sock = None
                state.pod_connected = False
        print(f"🔴 Lectern Pod Disconnected from {addr[0]}")
        client_sock.close()

    def _dispatch_message(self, line):
        try:
            msg = json.loads(line)
            event_type = msg.get("event")

            # 1. Keypad Event from ESP32 (TTP229)
            if event_type == "key" and self.on_key:
                key_num = msg.get("key")
                if key_num is not None:
                    self.on_key(int(key_num))

            # 2. NFC Card Event from ESP32 (PN532)
            elif event_type == "nfc" and self.on_nfc:
                uid_str = msg.get("uid", "").upper()
                mapped_val = NFC_MAP.get(uid_str)
                if mapped_val:
                    self.on_nfc(mapped_val)
                else:
                    print(f"ℹ️  Unregistered NFC Card UID: {uid_str}")

            # 3. Heartbeat telemetry
            elif event_type == "heartbeat":
                state.pod_connected = True
                state.pod_last_seen = time.time()

        except json.JSONDecodeError:
            print(f"⚠️  Malformed telemetry from Pod: {line}")
        except Exception as e:
            print(f"⚠️  Pod event dispatch error: {e}")

