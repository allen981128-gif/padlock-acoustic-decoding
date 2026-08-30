@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment was not found.
    echo Run setup_app.bat first.
    pause
    exit /b 1
)

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q PadlockCollector.spec 2>nul

".venv\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name PadlockCollector ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --add-data "model_assets;model_assets" ^
  app.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

copy /y settings.json "dist\PadlockCollector\settings.json" >nul 2>nul

echo.
echo Build completed:
echo dist\PadlockCollector\PadlockCollector.exe
pause
endlocal
