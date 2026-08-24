# Build the Windows GUI exe (onefile, windowed).
# Requires: pip install -e ".[dev,audio,gui]"
Write-Host "==> Installing/upgrading build deps" -ForegroundColor Cyan
pip install -q pyinstaller

Write-Host "==> Cleaning old builds" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
pyinstaller battery_gui.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

$exe = "dist/battery-music-gui.exe"
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "OK -> $exe (${mb} MB)" -ForegroundColor Green
    Write-Host "NOTE: unsigned exe triggers SmartScreen ('More info' -> 'Run anyway')." -ForegroundColor Yellow
} else {
    Write-Error "dist/battery-music-gui.exe not found"
    exit 1
}
