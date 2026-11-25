# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spezifikation: eine EXE, ohne Konsole, mit Icon.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("assets/icon.ico", "assets")]
datas += collect_data_files("customtkinter")          # Themes/Fonts
datas += collect_data_files("tkinterdnd2")            # tkdnd-DLLs/Tcl-Dateien

a = Analysis(
    ["src/berichtsheft/__main__.py"],
    pathex=["src"],
    datas=datas,
    hiddenimports=collect_submodules("berichtsheft") + ["tkinterdnd2"],
    excludes=["pytest", "PIL.ImageQt", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Berichtsheft-Assistent",
    icon="assets/icon.ico",
    console=False,          # --windowed
    upx=False,
    runtime_tmpdir=None,
)
