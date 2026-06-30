@echo off
echo 🎵 Initializing Battery Music Notifier setup for Windows...

:: Check if Python is installed and accessible in the system PATH
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ ERROR: Python was not found in your system PATH.
    echo 👉 Please install Python and check the "Add Python to PATH" option during setup.
    pause
    exit /b 1
)

echo 🐍 Bundling Python dependencies and registering executable commands...
pip install -e .

if %errorlevel% neq 0 (
    echo ❌ ERROR: Pip installation failed.
    pause
    exit /b %errorlevel%
)

echo ============================================================
echo 🎉 SUCCESS: Windows installation complete!
echo 👉 Run "battery-music doctor" to verify your configurations.
echo ============================================================
pause