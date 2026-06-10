# 基于 RV1126 的嵌入式音视频推流项目——全记录与开发指南

本文档完整记录了基于 Rockchip RV1126 开发板实现"声画同步、软件增益、浏览器实时观看"项目的全链路调试过程、踩坑记录及最终技术方案。可作为新板子重新配置时的开荒指南与项目技术总结。

---

## 一、项目架构总览

### 最终架构：板端采集 → Windows 转码 → 浏览器观看

```
U2 板子 (192.168.137.x)              Windows 宿主机                      浏览器 (局域网)
┌──────────────────────────┐  TCP:8080  ┌───────────────────────────┐  HTTP:8090  ┌──────────────┐
│ GStreamer                │───────────▶│ FFmpeg (MKV → H.264+AAC)  │◀────────────│ index.html   │
│ v4l2src + alsasrc        │            │ HLS 切片 (1s 分段)          │            │ hls.js 播放  │
│ → matroskamux → tcpsink  │            │ Python ThreadingHTTPServer │            │ 音频频谱动画  │
└──────────────────────────┘            │ FFmpeg 断流自动重连         │            └──────────────┘
                                        └───────────────────────────┘
```

- **板端**：GStreamer 采集音视频 → MKV 封装 → TCP 裸流推到 8080 端口（不变）
- **Windows 端**：FFmpeg 拉 TCP 流 → 解码 → 编码 H.264+AAC → HLS 切片 → Python HTTP 服务器分发
- **浏览器端**：hls.js 拉 HLS 流播放，Web Audio API 显示频谱，延迟约 5-8 秒

### 1. 硬件组成

| 硬件 | 型号 | 接口 | 角色 |
|------|------|------|------|
| 核心主控板 | Xiaomi AIoT U2-RV1126 (Rockchip RV1126) | ARM 嵌入式 Linux | 系统大脑，采集+封装+推流 |
| 音频采集 | S3 音频扩展板 (PDM 麦克风阵列) | 数字接口 `hw:0,1`，4 通道 | 环境音采集 |
| 视频输入 | S4 USB 摄像头 | `/dev/video25`，640x480@30fps MJPEG | 画面采集 |
| 扬声器 | E4 Speaker 子板 | 模拟接口 `plughw:0,0` | 音频播放 |
| 工作站 | Windows 10/11 + VMware Ubuntu VM | 网线直连板子 (ICS 共享网络) | 开发调试 + 转码分发 |

### 2. 软件技术栈

| 层级 | 技术 | 作用 |
|------|------|------|
| 板端采集引擎 | GStreamer 1.0 (`v4l2src`, `alsasrc`, `matroskamux`, `tcpserversink`) | 音视频抓取、增益、封装、推 TCP 裸流 |
| Windows 转码引擎 | FFmpeg (`libx264`, `aac`, `hls`) | MKV 解码 → H.264+AAC 编码 → HLS 切片 |
| Windows HTTP 服务 | Python 3 (`http.server.ThreadingHTTPServer`) | 多线程提供 index.html + HLS 文件 |
| 浏览器播放 | hls.js 1.5 + Web Audio API | HLS 拉流解码 + 音频频谱可视化 |
| 开发调试 | ADB, ALSA (alsamixer/amixer), V4L2 | 板端 Shell 访问、底层音频调优 |
| VM 辅助 | VMware Ubuntu + GStreamer | 反向音频管道 (PC 麦克风 → 板子扬声器) |

---

## 二、板端操作：新板子开荒标准化流程

### 第一阶段：网络初始化

```bash
# 查看网口状态
ifconfig eth0

# 获取 DHCP 地址（若无 IP）
udhcpc -i eth0

# 推荐：设置静态 IP（避免重启后 IP 变化）
ifconfig eth0 192.168.137.59 netmask 255.255.255.0 up
route add default gw 192.168.137.1
```

### 第二阶段：时钟校准

```bash
cd /tmp
export HOME=/tmp
date -s "2026-06-03 13:15:00"
```

### 第三阶段：启动 GStreamer 音视频推流管道

```bash
gst-launch-1.0 -v matroskamux name=mux streamable=true ! tcpserversink host=0.0.0.0 port=8080 \
v4l2src device=/dev/video25 ! image/jpeg,width=640,height=480,framerate=30/1 ! jpegparse ! queue ! mux. \
alsasrc device=hw:0,1 ! audio/x-raw,format=S16LE,rate=16000,channels=4 ! \
audioconvert ! audioamplify amplification=5.0 ! \
audioresample ! "audio/x-raw,channels=2" ! queue ! mux.
```

看到 `Setting pipeline to PLAYING...` 即成功。保持窗口运行，切勿关闭。

---

## 三、Windows 端操作：一键启动网页直播服务

### 前置依赖

```cmd
# 检查环境
python --version      # Python 3 必须
ffmpeg -version       # FFmpeg 必须
```

### 使用方式

```powershell
cd F:\物联网工程\rv1126-stream

# 测试模式（不需要板子，模拟彩条画面验证前端链路）
python start.py --test

# 正常模式（板子推流已启动）
python start.py                           # 默认 192.168.137.59:8080 → :8090
python start.py 192.168.137.9 8080 8090   # 指定板子 IP 和端口
```

### start.py 核心特性

- **FFmpeg 断流自动重连**：板端重启或网络闪断后，FFmpeg 自动清理旧分段 → 等待板子恢复 → 重新连接转码
- **多线程 HTTP 服务器**：`ThreadingHTTPServer`，多人同时观看不排队
- **Ctrl+C 一键全停**：FFmpeg 和 HTTP 服务器同时清理退出

### 浏览器打开

脚本打印的地址（例如 `http://192.168.1.100:8090`），同一局域网内任意设备浏览器打开即可。若其他设备无法访问，检查 Windows 防火墙：

```cmd
netsh advfirewall firewall add rule name="RV1126 Stream" dir=in action=allow protocol=tcp localport=8090
```

---

## 四、前端页面功能

`index.html` 提供完整的浏览器端观看体验：

| 功能 | 实现 |
|------|------|
| 视频播放 | hls.js 拉 HLS 流，自动播放 |
| 音频频谱 | Web Audio API + Canvas 48 条彩色柱状图，有声音就跳动 |
| 状态指示 | 绿点=直播中，黄点=加载中，红点=错误 |
| 一键开声音 | 默认静音（浏览器策略），点击按钮取消静音 |
| 断流恢复 | hls.js 自动重连，无需手动刷新 |

---

## 五、核心问题解决记录

### 1. 音频全 0 数据（静音）

- **原因**：S3 扩展板硬件拨码固定为 4 通道模式，I2S/PDM 时钟强绑 4 通道时序。软件以 2 通道采集导致时钟无法对齐。
- **对策**：GStreamer `alsasrc` 强制 `channels=4`，管道内部通过 `audioconvert` + `audioresample` 降混为双声道输出。

### 2. 数字麦克风音量极小（增益不足）

- **原因**：RK809 芯片音频驱动未暴露 `Mic Boost` 控制接口，无法从底层寄存器放大。
- **对策**：放弃底层驱动，在 GStreamer 管道中加 `audioamplify amplification=5.0` 实施软件增益，声音饱满无破音。

### 3. ALSA 底层混音器配置（扬声器无声）

- **发现**：`alsamixer` 中 rk809 驱动的 `Playback Path` 设为 `SPK_HP` 时，音频流绕过 `Master` 控制器，由 `Digital` 核心增益管辖。
- **解决方案**：

```bash
amixer -c 0 sset 'Playback Path' 'SPK_HP'
amixer -c 0 sset 'Digital' 100%
amixer -c 0 sset 'Master' unmute
sudo alsactl store   # 写入 asound.state，掉电不丢失
```

### 4. 板端 IP 不固定

- **现象**：板子 DHCP 获取的 IP 从 `192.168.137.59` 变为 `192.168.137.9`。
- **对策**：设置静态 IP（见第二阶段）。

### 5. 音频硬件双向并行冲突（未完全解决）

- **现象**：板子无法同时在 4 通道录音（8080 端口上行）和双通道播放（反向音频下行）时正常工作。
- **AI 诊断**：RK809 音频 Codec 的录音核心与播放核心共享硬件时钟，物理层面不支持"4ch 录音 + 双声道播放"同时进行，AI 结论可靠性未验证。
- **当前处理**：课程大作业不要求双向同时通信，仅做记录下来。

### 6. FFmpeg + lavfi 在 Windows Python subprocess 下的兼容性问题

- **现象**：测试模式中 FFmpeg `-f lavfi` 在 `subprocess.Popen` 里不产出文件也不报错。
- **对策**：测试模式改为 Python 直接生成模拟画面页面（Canvas 彩条动画），绕过 FFmpeg lavfi。正式推流模式（TCP 输入）不受影响。

---

## 六、音频反向传输：PC 麦克风 → 板子扬声器

实现远程对讲/喊话功能（于 VMware Ubuntu 虚拟机上运行）。

### 板端先启动接收服务（监听 8081）

```bash
gst-launch-1.0 -v tcpserversrc host=0.0.0.0 port=8081 ! \
    rawaudioparse use-sink-caps=false format=pcm pcm-format=s16le sample-rate=16000 num-channels=1 ! \
    audioconvert ! audioamplify amplification=15.0 ! \
    alsasink device=plughw:0,0 sync=false
```

### VM 端发送音频

```bash
gst-launch-1.0 -v autoaudiosrc ! audioconvert ! audioresample ! \
    audio/x-raw,rate=16000,channels=1,format=S16LE ! \
    tcpclientsink host=192.168.137.59 port=8081
```

> 操作顺序：先启动板端接收 → 再启动 VM 端发送。

---

## 七、历史方案：cpolar 公网穿透（已废弃）

> 当前架构为局域网浏览器观看，公网穿透方案仅作历史记录。

- **ngrok**：免费版需绑信用卡（错误 `ERR_NGROK_8013`），已废弃。
- **cpolar**：国内穿透工具，免费版原生支持 TCP，曾用于将板子 8080 端口映射为 `tcp://1.tcp.cpolar.cn:xxxxx` 公网地址。当前不需要穿透，相关操作见 `vm_commands.md`。

---

## 八、常用命令速查

| 场景 | 命令 |
|------|------|
| 查看视频设备 | `v4l2-ctl --list-devices` |
| 测试麦克风 | `arecord -D hw:0,1 -c 4 -r 16000 -f S16_LE -V mono test4.wav` |
| 测试扬声器 | `speaker-test -D plughw:0,0 -t wav -c 2` |
| ALSA 调音 | `export TERM=xterm && alsamixer` |
| 查看板子 IP | `ifconfig eth0 \| grep inet` |
| ADB 连接 | `adb shell` |
| 网页测试模式 | `python start.py --test` |
| 正常启动服务 | `python start.py [板子IP] [板子端口] [HTTP端口]` |
| 防火墙放行 | `netsh advfirewall firewall add rule name="RV1126 Stream" dir=in action=allow protocol=tcp localport=8090` |
