@echo off
REM install-deps.bat - Install FFmpeg + Python on Windows
REM Run as Administrator for choco install

echo ============================================
echo  RV1126 Stream - Windows Dependency Check
echo ============================================
echo.

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [MISSING] Python 3
    echo   Download: https://www.python.org/downloads/
    echo   OR: winget install Python.Python.3.12
) else (
    echo [OK] Python found
)

REM Check FFmpeg
where ffmpeg >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [MISSING] FFmpeg
    echo   Download: https://ffmpeg.org/download.html
    echo   OR: winget install Gyan.FFmpeg
    echo.
    echo   After install, make sure ffmpeg.exe is in your PATH
) else (
    echo [OK] FFmpeg found
)

echo.
echo Once both are OK, run: powershell -ExecutionPolicy Bypass .\start.ps1
pause
