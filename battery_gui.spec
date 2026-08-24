# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: battery-music-gui onefile (windowed) for Windows.
# Build:  pyinstaller battery_gui.spec --noconfirm   (or scripts/build_gui_exe.ps1)

import os

block_cipher = None

datas = [
    ("battery_notifier/gui/web", "battery_notifier/gui/web"),
    ("battery_notifier/assets", "battery_notifier/assets"),
]

a = Analysis(
    ["entry_gui.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # pywebview picks a backend at runtime; make sure the EdgeChromium
        # one is bundled even though it is imported dynamically.
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        # pystray loads its platform backend dynamically as well
        "pystray._win32",
        # qrcode's PIL factory
        "qrcode",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="battery-music-gui",
    console=False,           # windowed: no console flash
    disable_windowed_traceback=False,
    upx=False,               # UPX triggers AV false positives; skip it
)
