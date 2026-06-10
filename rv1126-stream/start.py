#!/usr/bin/env python3
"""RV1126 Browser Stream Server - Python 版一键启动

用法:
  python start.py                           # 默认连接板子 192.168.137.59:8080
  python start.py <board_ip> <board_port> <http_port>
  python start.py --test                    # 测试模式（模拟画面，不需要板子/FFmpeg）

特性:
  - FFmpeg 断流自动重连
  - 多线程 HTTP 服务器
  - 浏览器按住说话 → 板子扬声器（WebSocket 音频中继）
"""

import socket
import subprocess
import sys
import time
import shutil
import struct
import hashlib
import base64
import threading
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler


SCRIPT_DIR = Path(__file__).resolve().parent
WEB_DIR = Path(tempfile.gettempdir()) / "rv1126-stream-web"
HLS_DIR = WEB_DIR / "hls"

# 音频中继：浏览器 WebSocket → 板子 8081 端口
AUDIO_RELAY_PORT = 8082
BOARD_REVERSE_PORT = 8081

C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
     "red": "\033[31m", "white": "\033[37m", "gray": "\033[90m",
     "reset": "\033[0m"}

def log(msg, color="white"):
    print(f"{C.get(color, '')}{msg}{C['reset']}")

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())

def check_board(ip, port, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


# ========== 测试页面 ==========
TEST_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RV1126 - 测试模式</title>
<style>
  *,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
  body{background:#0f0f1a;color:#e0e0e0;font-family:"Microsoft YaHei",sans-serif;display:flex;flex-direction:column;align-items:center;min-height:100vh;padding:20px}
  header{text-align:center;margin-bottom:16px}
  header h1{font-size:1.3rem;color:#5ec4ff}
  header .sub{font-size:.78rem;color:#666;margin-top:4px}
  #player-wrapper{width:100%;max-width:880px;background:#000;border-radius:10px 10px 0 0;overflow:hidden}
  canvas{width:100%;display:block;aspect-ratio:4/3;background:#000}
  #status-bar{display:flex;align-items:center;gap:10px;padding:10px 16px;font-size:.8rem;background:#111122;border-top:1px solid #1a1a2e}
  #status-dot{width:8px;height:8px;border-radius:50%;background:#30d070;box-shadow:0 0 6px #30d070}
  #viz-wrapper{width:100%;max-width:880px;background:#0a0a16;border-radius:0 0 10px 10px;padding:8px 16px 12px;margin-bottom:16px}
  #viz-label{font-size:.7rem;color:#555;display:flex;align-items:center;gap:6px;margin-bottom:4px}
  #viz-dot{width:6px;height:6px;border-radius:50%;background:#30d070}
  #viz-canvas{width:100%;height:48px;display:block}
  .info-row{font-size:.75rem;color:#555;text-align:center}
</style>
</head>
<body>
<header><h1>RV1126 物联网摄像头实时监控</h1><p class="sub">[测试模式] 模拟画面 &middot; 无需板子 &middot; 全链路验证</p></header>
<div id="player-wrapper">
  <canvas id="video-canvas"></canvas>
  <div id="status-bar"><span id="status-dot"></span><span>测试模式  |  模拟音视频流  |  前端正常工作中</span></div>
</div>
<div id="viz-wrapper"><div id="viz-label"><span id="viz-dot"></span> 音频波形（模拟）</div><canvas id="viz-canvas"></canvas></div>
<div class="info-row">页面渲染正常，连接板子后切换到实际画面。</div>
<script>
(function(){
  var vc=document.getElementById('video-canvas');
  var ac=document.getElementById('viz-canvas');
  var vctx=vc.getContext('2d'),actx=ac.getContext('2d');
  var t=0,frame=0,barH=Array.from({length:48},function(){return 0});
  function rv(){vc.width=vc.clientWidth*devicePixelRatio;vc.height=vc.clientHeight*devicePixelRatio}
  function ra(){ac.width=ac.clientWidth*devicePixelRatio;ac.height=ac.clientHeight*devicePixelRatio}
  rv();ra();window.addEventListener('resize',function(){rv();ra()});
  function dv(){
    var w=vc.width,h=vc.height;
    var cs=['#ffffff','#ffff00','#00ffff','#00ff00','#ff00ff','#ff0000','#0000ff','#000000'];
    var bw=w/cs.length;
    for(var i=0;i<cs.length;i++){vctx.fillStyle=cs[i];vctx.fillRect(i*bw,0,bw,h)}
    vctx.fillStyle='rgba(0,0,0,0.5)';vctx.fillRect(0,h*0.35,w,h*0.3);
    vctx.fillStyle='#fff';vctx.font=(h*0.12)+'px "Microsoft YaHei",sans-serif';vctx.textAlign='center';
    vctx.fillText('RV1126 Browser Stream Server',w/2,h*0.5);
    vctx.fillText('Web Frontend Working',w/2,h*0.5+h*0.09);
    var x=(t*80)%(w+200)-100;
    vctx.fillStyle='rgba(255,255,255,0.3)';vctx.fillRect(x,0,3,h);
    vctx.fillStyle='#fff';vctx.font=(h*0.04)+'px monospace';vctx.textAlign='right';
    vctx.fillText(new Date().toLocaleTimeString(),w-20,h-20);
  }
  function da(){
    var w=ac.width,h=ac.height;actx.clearRect(0,0,w,h);
    for(var i=0;i<48;i++){
      var target=20+Math.sin(t*0.1+i*0.4)*60+Math.sin(t*0.17+i*0.23)*30+Math.random()*10;
      barH[i]=barH[i]*0.8+target*0.2;
      var bh=Math.max(2,barH[i]/100*h);
      var bw=w/48*0.7,gap=w/48*0.3;
      actx.fillStyle='rgb('+Math.floor(barH[i]/100*40)+','+Math.floor(100+barH[i]/100*155)+','+Math.floor(200-barH[i]/100*100)+')';
      actx.fillRect(i*(bw+gap),h-bh,bw,bh);
    }
    document.getElementById('viz-dot').style.boxShadow='0 0 '+(6+Math.random()*6)+'px #30d070';
  }
  function loop(){t+=0.016;frame++;dv();if(frame%2===0)da();requestAnimationFrame(loop);}
  loop();
})();
</script>
</body>
</html>"""


# ========== WebSocket 音频中继服务器 ==========
def ws_audio_relay(board_ip):
    """
    WebSocket 服务器（8082 端口）：
    接收浏览器发来的 Int16 PCM 音频帧，通过 TCP 转发到板子 8081 端口。
    """
    WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def parse_ws_frame(data):
        """解析 WebSocket 帧，返回 unmasked payload。只处理二进制帧。"""
        if len(data) < 2:
            return None
        opcode = data[0] & 0x0F
        masked = (data[1] & 0x80) != 0
        length = data[1] & 0x7F
        idx = 2
        if length == 126:
            if len(data) < 4:
                return None
            length = struct.unpack(">H", data[2:4])[0]
            idx = 4
        elif length == 127:
            if len(data) < 10:
                return None
            length = struct.unpack(">Q", data[2:10])[0]
            idx = 10
        if masked:
            if len(data) < idx + 4:
                return None
            mask = data[idx:idx + 4]
            idx += 4
        if len(data) < idx + length:
            return None
        payload = bytearray(data[idx:idx + length])
        if masked:
            for i in range(length):
                payload[i] ^= mask[i % 4]
        return bytes(payload), idx + length

    def build_ws_frame(payload):
        """构建无掩码 WebSocket 文本帧"""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        frame = bytearray()
        frame.append(0x81)  # FIN + text opcode
        length = len(payload)
        if length < 126:
            frame.append(length)
        else:
            frame.append(126)
            frame.extend(struct.pack(">H", length))
        frame.extend(payload)
        return bytes(frame)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.settimeout(2)

    try:
        server.bind(("0.0.0.0", AUDIO_RELAY_PORT))
        server.listen(5)
        log(f"Audio relay WebSocket on port {AUDIO_RELAY_PORT}", "green")
    except OSError as e:
        log(f"WARNING: Cannot bind audio relay port {AUDIO_RELAY_PORT}: {e}", "yellow")
        log("  Browser talkback will not work.", "gray")
        return

    while not _stop_flag.is_set():
        try:
            client, addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        log(f"Audio client connected: {addr[0]}", "green")
        board_sock = None

        try:
            # WebSocket 握手
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(4096)
                if not chunk:
                    raise Exception("No HTTP upgrade request")
                data += chunk
                if len(data) > 8192:
                    raise Exception("Request too large")

            request = data.decode("utf-8", errors="replace")
            key_match = None
            for line in request.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key_match = line.split(":", 1)[1].strip()
            if not key_match:
                raise Exception("No WebSocket key")

            accept = base64.b64encode(
                hashlib.sha1((key_match + WS_GUID).encode()).digest()
            ).decode()

            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            )
            client.sendall(response.encode())

            # 连接板子 8081
            board_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            board_sock.settimeout(5)
            board_sock.connect((board_ip, BOARD_REVERSE_PORT))
            log(f"  Relay: browser → board {board_ip}:{BOARD_REVERSE_PORT}", "gray")

            # 中继循环
            buf = b""
            while not _stop_flag.is_set():
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    result = parse_ws_frame(buf)
                    if result is None:
                        break
                    payload, consumed = result
                    buf = buf[consumed:]
                    if payload:
                        try:
                            board_sock.sendall(payload)
                        except Exception:
                            break
                if len(buf) > 65536:
                    buf = b""  # 溢出了，丢弃

        except Exception as e:
            log(f"Audio relay error: {e}", "yellow")

        finally:
            if board_sock:
                try:
                    board_sock.close()
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass
            log("Audio client disconnected.", "gray")


# ========== FFmpeg 看门狗 ==========
_stop_flag = threading.Event()

def ffmpeg_watchdog(board_ip, board_port):
    retry_delay = 3
    restart_count = 0

    while not _stop_flag.is_set():
        restart_count += 1
        if restart_count > 1:
            log(f"FFmpeg restart attempt #{restart_count - 1}...", "yellow")

        for f in HLS_DIR.glob("*.ts"):
            f.unlink(missing_ok=True)
        m3u8 = HLS_DIR / "stream.m3u8"
        m3u8.unlink(missing_ok=True)

        while not _stop_flag.is_set():
            if check_board(board_ip, board_port, timeout=2):
                break
            log("  Waiting for board to become reachable...", "gray")
            time.sleep(retry_delay)

        if _stop_flag.is_set():
            break

        log("Starting FFmpeg...", "green")

        ffmpeg_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err",
            "-probesize", "32768", "-analyzeduration", "500000",
            "-i", f"tcp://{board_ip}:{board_port}",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", "2000k", "-g", "30", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "hls",
            "-hls_time", "1",
            "-hls_list_size", "3",
            "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-hls_flags", "delete_segments",
            "-hls_segment_filename", str(HLS_DIR / "segment_%05d.ts"),
            str(m3u8),
        ]

        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.DEVNULL)
        log(f"FFmpeg running (PID: {proc.pid})", "green")

        proc.wait()
        if _stop_flag.is_set():
            break

        log(f"FFmpeg exited (code {proc.returncode}). Will restart in {retry_delay}s...", "yellow")
        time.sleep(retry_delay)


# ========== 主流程 ==========
def main():
    args = sys.argv[1:]
    test_mode = "--test" in args
    if test_mode:
        args.remove("--test")

    board_ip   = args[0] if len(args) > 0 else "192.168.137.59"
    board_port = int(args[1]) if len(args) > 1 else 8080
    http_port  = int(args[2]) if len(args) > 2 else 8090
    local_ip   = get_local_ip()

    log("=" * 48, "cyan")
    log(" RV1126 Browser Stream Server", "cyan")
    if test_mode:
        log(" [TEST MODE]", "yellow")
    log("=" * 48, "cyan")
    print()
    if test_mode:
        log("  Source: Simulated", "gray")
    else:
        log(f"  Board:      tcp://{board_ip}:{board_port}", "gray")
        log(f"  Talkback:   ws://{local_ip}:{AUDIO_RELAY_PORT} → board:{BOARD_REVERSE_PORT}", "gray")
    log(f"  Web page:   http://{local_ip}:{http_port}", "gray")
    print()

    # 准备目录
    if WEB_DIR.exists():
        shutil.rmtree(WEB_DIR)
    HLS_DIR.mkdir(parents=True)

    if test_mode:
        (WEB_DIR / "index.html").write_text(TEST_HTML, encoding="utf-8")
        log("Test page ready.", "green")
    else:
        shutil.copy(SCRIPT_DIR / "index.html", WEB_DIR)

        if shutil.which("ffmpeg") is None:
            log("ERROR: ffmpeg not found in PATH.", "red")
            sys.exit(1)

        log("Checking connection to board...", "yellow")
        if check_board(board_ip, board_port):
            log("Board reachable.", "green")
        else:
            log(f"WARNING: Cannot reach board at {board_ip}:{board_port}", "red")
            log("FFmpeg will keep retrying until board is online.", "gray")

        # 启动 FFmpeg 看门狗
        threading.Thread(target=ffmpeg_watchdog, args=(board_ip, board_port), daemon=True).start()

        # 启动 WebSocket 音频中继
        threading.Thread(target=ws_audio_relay, args=(board_ip,), daemon=True).start()

        # 等待 HLS 分段
        log("Waiting for first HLS segments...", "yellow")
        m3u8 = HLS_DIR / "stream.m3u8"
        seg0 = HLS_DIR / "segment_00000.ts"
        ready = False
        for i in range(120):
            if m3u8.exists() and seg0.exists():
                ready = True
                break
            if i % 10 == 0 and i > 0:
                log(f"  Still waiting... ({i * 0.5:.0f}s)", "gray")
            time.sleep(0.5)
        if ready:
            log("HLS segments ready.", "green")
        else:
            log("WARNING: HLS not ready yet. Server will start anyway.", "yellow")

    # HTTP 服务器
    log(f"Starting HTTP server on port {http_port}...", "yellow")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)
        def log_message(self, fmt, *args):
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", http_port), Handler)

    log("")
    log("=" * 48, "green")
    log("  STREAM IS LIVE", "green")
    if not test_mode:
        log("  Talkback: Press & hold button on web page", "green")
    log("=" * 48, "green")
    log("")
    log("  Open: http://" + local_ip + ":" + str(http_port), "cyan")
    log("  Press Ctrl+C to stop", "gray")
    log("=" * 48)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print()
        log("Shutting down...", "yellow")
        _stop_flag.set()
        httpd.shutdown()
        log("All services stopped.", "green")


if __name__ == "__main__":
    main()
