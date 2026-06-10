# RV1126 开发板命令速查手册

---

## 一、设备盘点

**`v4l2-ctl --list-devices`**

列出系统当前识别到的所有视频设备。确认摄像头挂载为 `/dev/video25`。

---

## 二、音频采集与播放测试

### `arecord -D hw:0,1 -c 4 -r 16000 -f S16_LE -V mono test4.wav`

从 S3 麦克风阵列录制音频。

| 参数 | 含义 |
|------|------|
| `-D hw:0,1` | 声卡 0 设备 1，越过软件混音层直连硬件 |
| `-c 4` | 4 通道采集，匹配 S3 拨码开关设定 |
| `-r 16000` | 16kHz 采样率 |
| `-f S16_LE` | 16 位有符号小端格式 |
| `-V mono` | 终端打印动态音量条，直观判断麦克风是否吸音 |

### `speaker-test -D plughw:0,0 -t wav -c 2`

直接向驱动发送 "Front Left"、"Front Right" 人声。判断喇叭响不响、左右声道有没有接反。

---

## 三、ALSA 底层调音

### `export TERM=xterm && alsamixer`

打开 ALSA 伪图形化调音台。核心发现：`Playback Path` 切为 `SPK_HP` 时，音频流绕过 `Master` 控制器，直接由 `Digital` 数字核心增益管辖。

### `amixer` 命令行固化

```bash
amixer -c 0 sset 'Playback Path' 'SPK_HP'   # 强制路由到扬声器功放
amixer -c 0 sset 'Digital' 100%              # 数字核心增益拉满
amixer -c 0 sset 'Master' unmute             # 解除静音
```

### `sudo alsactl store`

将当前调好的音量和通路状态写入底层配置文件（`asound.state`），掉电重启不丢失。

---

## 四、网络初始化

```bash
ifconfig eth0 up                       # 启用网口
udhcpc -i eth0                         # DHCP 获取地址
ifconfig eth0 | grep inet              # 查看当前 IP

# 设静态 IP（避免重启后 IP 变化）
ifconfig eth0 192.168.137.59 netmask 255.255.255.0 up
route add default gw 192.168.137.1
```

Windows 端 ICS 服务重启（板子 DHCP 一直 sending discover 无响应时）：

```cmd
net stop SharedAccess
net start SharedAccess
```
然后板子重新 `udhcpc -i eth0`。

---

## 五、正向推流（板端 → 电脑 / 浏览器）

板子作为 TCP 服务端（8080 端口），采摄像头 MJPEG + 4 通道麦克风，音频放大 5 倍后降混为双声道，MKV 封装后挂网。

```bash
gst-launch-1.0 -v matroskamux name=mux streamable=true ! tcpserversink host=0.0.0.0 port=8080 \
v4l2src device=/dev/video25 ! image/jpeg,width=640,height=480,framerate=30/1 ! jpegparse ! queue max-size-buffers=30 ! mux. \
alsasrc device=hw:0,1 do-timestamp=true ! audio/x-raw,format=S16LE,rate=16000,channels=4 ! \
audioconvert ! audioamplify amplification=5.0 ! \
audioresample ! "audio/x-raw,channels=2" ! queue max-size-buffers=100 max-size-time=2000000000 ! mux.
```

> 看到 `Setting pipeline to PLAYING...` 即成功。

**VLC 验证**：Ctrl+N → `tcp://<板子IP>:8080`

**Windows 网页服务**：

```powershell
cd F:\物联网工程\rv1126-stream
python start.py <板子IP> 8080 8090
```

浏览器打开脚本打印的地址。本机对讲用 `http://localhost:8090`，他人观看用 IP 地址。

**注意**：浏览器默认静音，点击"开声音"按钮后音频频谱应跳动。

---

## 六、反向对讲（浏览器 → 板子扬声器）

板端先启动接收管道（8081 端口），循环监听：

```bash
while true; do
  gst-launch-1.0 -v tcpserversrc host=0.0.0.0 port=8081 ! \
    rawaudioparse use-sink-caps=false format=pcm pcm-format=s16le sample-rate=16000 num-channels=1 ! \
    audioconvert ! audioamplify amplification=5.0 ! \
    alsasink device=plughw:0,0 sync=false
  echo "--- client disconnected, re-listening ---"
  sleep 1
done
```

> `amplification` 可调，值越大扬声器声音越大，建议 3.0~5.0。

**Windows 对讲服务器**：

```powershell
cd F:\物联网工程\rv1126-stream
python talkback_server.py 8090 <板子IP>
```

**浏览器**：用 `http://localhost:8090/talkback_test.html` 打开（必须 localhost，否则浏览器拒绝麦克风），按住圆形按钮说话。

---

## 七、限制与注意事项

| 问题 | 原因 | 应对 |
|------|------|------|
| 浏览器默认无声音 | HLS 自动播放策略要求静音 | 点击"开声音"按钮，同时唤醒 AudioContext |
| 非 localhost 不可用麦克风 | 浏览器安全策略：HTTP 非本地拒绝 getUserMedia | 演示者用 localhost 对讲，观众只看 |
| 正向反向不能同时开启 | RK809 音频芯片可能的硬件冲突 | 不要求同时双向 |
| FFmpeg MKV 解析报错 | MKV 从 TCP 中间接入无文件头 | FFmpeg 已加容错参数，跳过破损帧自动恢复 |
