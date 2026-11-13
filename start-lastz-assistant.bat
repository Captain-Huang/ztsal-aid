@echo off
setlocal EnableExtensions
rem UTF-8 script. Switch the console before any Chinese output.
chcp 65001 >nul
cd /d "%~dp0"
if /I "%~1"=="__run" goto run

set "PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo 找不到虚拟环境：%~dp0.venv\Scripts\python.exe
  echo 请先在仓库目录执行：
  echo   py -3.12 -m venv .venv
  echo   .\.venv\Scripts\python.exe -m pip install .
  pause
  exit /b 1
)

start "lastz-assistant" /MIN "%~f0" __run
exit /b 0

:run
set "LOGDIR=%~dp0logs"
set "LOG=%LOGDIR%\startup.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

set "PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"

set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

>>"%LOG%" echo.
>>"%LOG%" echo ===== %DATE% %TIME% 启动 =====
>>"%LOG%" echo 工作目录：%CD%
>>"%LOG%" echo Python：%PYTHON%

"%PYTHON%" -m lastz_assistant >>"%LOG%" 2>&1
set "CODE=%ERRORLEVEL%"
>>"%LOG%" echo ===== %DATE% %TIME% 退出 code=%CODE% =====
exit /b %CODE%