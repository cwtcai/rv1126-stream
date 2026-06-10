#!/usr/bin/env python3
"""浏览器对讲测试服务器 - 独立运行，不依赖 start.py

用法:
  python talkback_server.py                          # 默认 8090
  python talkback_server.py <http_port> <board_ip>   # 指定端口和板子 IP

功能:
  - HTTP 提供对讲测试页面
  - WebSocket 中继：浏览器音频 → 板子 8081 端口
"""

import socket
import sys
import struct
import hashlib
import base64
import threading
import json
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HTTP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
BOARD_IP = sys.argv[2] if len(sys.argv) > 2 else "192.168.137.59"
BOARD_REVERSE_PORT = 8081
WS_PORT = 8082

SCRIPT_DIR = Path(__file__).resolve().parent
_stop_flag = threading.Event()

C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
     "red": "\033[31m", "white": "\033[37m", "gray": "\033[90m", "reset": "\033[0m"}

def log(msg, color="white"):
    print(f"{C.get(color, '')}{msg}{C['reset']}")

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())


# ========== WebSocket 中继 ==========
def ws_relay():
    WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def parse_frame(data):
        if len(data) < 2:
            return None
        opcode = data[0] & 0x0F
        masked = (data[1] & 0x80) != 0
        length = data[1] & 0x7F
        idx = 2
        if length == 126:
            if len(data) < 4: return None
            length = struct.unpack(">H", data[2:4])[0]; idx = 4
        elif length == 127:
            if len(data) < 10: return None
            length = struct.unpack(">Q", data[2:10])[0]; idx = 10
        if masked:
            if len(data) < idx + 4: return None
            mask = data[idx:idx+4]; idx += 4
        if len(data) < idx + length: return None
        payload = bytearray(data[idx:idx+length])
        if masked:
            for i in range(length): payload[i] ^= mask[i % 4]
        return bytes(payload), idx + length

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.settimeout(2)

    try:
        server.bind(("0.0.0.0", WS_PORT))
        server.listen(5)
    except OSError as e:
        log(f"Cannot bind WS port {WS_PORT}: {e}", "red")
        return

    while not _stop_flag.is_set():
        try:
            client, addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        log(f"Audio client: {addr[0]}", "green")
        board = None

        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(4096)
                if not chunk: raise Exception("no data")
                data += chunk

            key = None
            for line in data.decode("utf-8", "replace").split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            if not key: raise Exception("no key")

            accept = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode()).digest()
            ).decode()
            client.sendall(
                f"HTTP/1.1 101 Switching Protocols\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
            )

            board = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            board.settimeout(5)
            board.connect((BOARD_IP, BOARD_REVERSE_PORT))
            log(f"  → board {BOARD_IP}:{BOARD_REVERSE_PORT}", "gray")

            buf = b""
            while not _stop_flag.is_set():
                chunk = client.recv(4096)
                if not chunk: break
                buf += chunk
                while True:
                    r = parse_frame(buf)
                    if r is None: break
                    pcm, consumed = r
                    buf = buf[consumed:]
                    if pcm:
                        try:
                            board.sendall(pcm)
                        except Exception:
                            break
                if len(buf) > 65536: buf = b""
        except Exception as e:
            log(f"Relay error: {e}", "yellow")
        finally:
            if board:
                try: board.close()
                except: pass
            try: client.close()
            except: pass
            log("Audio client disconnected.", "gray")


# ========== HTTP 服务器 ==========
def main():
    local_ip = get_local_ip()

    # 检查对讲测试页面
    test_page = SCRIPT_DIR / "talkback_test.html"
    if not test_page.exists():
        log("ERROR: talkback_test.html not found!", "red")
        sys.exit(1)

    log("=" * 44, "cyan")
    log(" Talkback Test Server", "cyan")
    log("=" * 44, "cyan")
    print()
    log(f"  WebSocket : ws://{local_ip}:{WS_PORT}", "gray")
    log(f"  Board     : {BOARD_IP}:{BOARD_REVERSE_PORT}", "gray")
    log(f"  Web page  : http://{local_ip}:{HTTP_PORT}", "gray")
    print()

    # 启动 WebSocket 中继
    threading.Thread(target=ws_relay, daemon=True).start()

    # 检查板子
    log("Checking board...", "yellow")
    try:
        s = socket.create_connection((BOARD_IP, BOARD_REVERSE_PORT), timeout=3)
        s.close()
        log("Board reachable.", "green")
    except Exception:
        log(f"WARNING: Cannot reach {BOARD_IP}:{BOARD_REVERSE_PORT}", "red")
        log("Start reverse pipeline on board first.", "gray")

    # 启动 HTTP 服务器
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)
        def log_message(self, f, *a):
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)

    log("")
    log("=" * 44, "green")
    log("  TALKBACK SERVER RUNNING", "green")
    log("=" * 44, "green")
    log("")
    log(f"  Open: http://{local_ip}:{HTTP_PORT}/talkback_test.html", "cyan")
    log(f"  Press Ctrl+C to stop", "gray")
    log("=" * 44)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print()
        log("Shutting down...", "yellow")
        _stop_flag.set()
        httpd.shutdown()
        log("Done.", "green")


if __name__ == "__main__":
    main()
