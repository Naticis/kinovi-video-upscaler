@echo off
setlocal

echo Building Kinovi Video Upscaler...
docker build -t kinovi-video-upscaler:0.1 .
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo.
echo Build complete: kinovi-video-upscaler:0.1
endlocal
