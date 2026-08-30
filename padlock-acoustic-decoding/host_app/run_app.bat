@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Running first-time setup...
    call setup_app.bat auto
    if errorlevel 1 (
        echo.
        echo Setup failed.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" app.py
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo Padlock Collector exited with error code %APP_EXIT%.
    echo.
    echo Checking MAIN v8 Recognition dependencies...
    ".venv\Scripts\python.exe" -c "import numpy, soundfile; print('numpy/soundfile: OK'); import scipy; print('scipy:', scipy.__version__)"
    echo.
    echo If scipy is missing, run setup_app.bat once, then start the App again.
    echo If another traceback is shown above, send a screenshot of this window.
    pause
)
endlocal & exit /b %APP_EXIT%
