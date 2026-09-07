# PyInstaller spec for SVMixer (Windows build).
#
# Run this ON WINDOWS (PyInstaller does not cross-compile) from the repo
# root, with the project's virtualenv active:
#
#   pyinstaller packaging/windows/SVMixer.spec --noconfirm
#
# Output goes to dist/SVMixer/ (one-folder build — starts faster and is
# easier to debug missing-module errors than --onefile). See
# BUILD_WINDOWS.md for the full walkthrough, including how to turn this
# into a proper Setup.exe installer with Inno Setup.

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
project_root = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))

# librosa and soundfile both pull in optional/dynamically-imported
# submodules (numba, llvmlite, audioread, etc.) that PyInstaller's static
# analysis can miss -- collect_all pulls in their full submodule/data/
# binary graph rather than hand-listing hidden imports one crash at a time.
datas = []
binaries = []
hiddenimports = [
    "PySide6.QtMultimedia",
]
for package in ("librosa", "soundfile", "pydub"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# Bundled fonts + logo/icon assets (anything not reached via `import` has
# to be listed explicitly so PyInstaller copies it into the build).
datas += [
    (os.path.join(project_root, "app", "ui", "assets", "fonts"), "app/ui/assets/fonts"),
    (os.path.join(project_root, "app", "ui", "assets", "logo"), "app/ui/assets/logo"),
]

a = Analysis(
    [os.path.join(project_root, "run_app.py")],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SVMixer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app -- no console window
    icon=os.path.join(project_root, "app", "ui", "assets", "logo", "SV.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SVMixer",
)
