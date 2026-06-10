# RV1126 浏览器端实时直播系统

## 系统架构

```
U2 板子 (192.168.137.59)              Windows 电脑                       浏览器 (局域网)
+----------------------------+  TCP:8080  +---------------------------+  HTTP:8090  +----------+
| GStreamer (MKV → tcpsink)  |----------->| FFmpeg (MKV → HLS 转码)    |<------------| hls.js   |
+----------------------------+           | Python HTTP 服务器          |            +----------+
                                         +---------------------------+
```

## 环境配置（一次性）

1. 安装 [Python 3](https://www.python.org/downloads/)（安装时勾选 "Add to PATH"）
2. 安装 [FFmpeg](https://ffmpeg.org/download.html)（或命令行执行 `winget install Gyan.FFmpeg`）
3. 运行 `install-deps.bat` 检查依赖是否就绪

## 使用步骤

### 第一步：启动板端推流（通过 adb shell 进入板子）

```bash
gst-launch-1.0 -v matroskamux name=mux streamable=true ! tcpserversink host=0.0.0.0 port=8080 \
v4l2src device=/dev/video25 ! image/jpeg,width=640,height=480,framerate=30/1 ! jpegparse ! queue ! mux. \
alsasrc device=hw:0,1 ! audio/x-raw,format=S16LE,rate=16000,channels=4 ! \
audioconvert ! audioamplify amplification=5.0 ! \
audioresample ! "audio/x-raw,channels=2" ! queue ! mux.
```

看到终端输出 `Setting pipeline to PLAYING...` 即表示推流成功。

### 第二步：启动网页服务器（Windows PowerShell）

```powershell
powershell -ExecutionPolicy Bypass .\start.ps1
```

### 第三步：浏览器打开观看

在任意同一局域网内的设备浏览器中，访问脚本打印的地址（例如 `http://192.168.1.100:8090`）。

## 注意事项

- 视频默认静音播放（浏览器策略限制），点击播放器右下角小喇叭图标即可开启声音
- 延迟约 6-10 秒（HLS 分段缓冲机制）
- 如果页面短暂报错，等待几秒即可自动恢复，无需手动刷新
