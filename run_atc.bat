@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Сначала выполните установку. Кратко: README.md, подробно: docs\wiki\Установка.md
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m ru_atc %*
pause
