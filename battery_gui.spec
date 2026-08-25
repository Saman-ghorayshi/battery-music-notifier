# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: battery-music-gui onefile (windowed) for Windows.
# Build:  pyinstaller battery_gui.spec --noconfirm   (or scripts/build_gui_exe.ps1)

import os

from battery_notifier import __version__ as APP_VERSION

block_cipher = None

# ---- Windows version resource (Properties -> Details) ----------------------
_parts = [int(x) for x in APP_VERSION.split(".")]
while len(_parts) < 4:
    _parts.append(0)
_filevers = tuple(_parts[:4])
_verstr = ".".join(str(p) for p in _filevers)

VERSION_FILE = "build_version.txt"  # written next to the spec; gitignored? no - regenerated every build
with open(VERSION_FILE, "w", encoding="utf-8") as _vf:
    _vf.write(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_filevers},
    prodvers={_filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Saman'),
        StringStruct('FileDescription', 'Battery Music Notifier - thief catcher and battery alerts'),
        StringStruct('FileVersion', '{_verstr}'),
        StringStruct('InternalName', 'battery-music-gui'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', 'battery-music-gui.exe'),
        StringStruct('ProductName', 'Battery Music Notifier'),
        StringStruct('ProductVersion', '{_verstr}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

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
    version=VERSION_FILE,     # Properties -> Details panel
    icon="battery_notifier/assets/icon.ico",
    console=False,            # windowed: no console flash
    disable_windowed_traceback=False,
    upx=False,                # UPX triggers AV false positives; skip it
)
