# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 exe，内嵌器件包。

用法：build.bat 或
  .venv\Scripts\pyinstaller.exe --noconfirm --clean build\DAPLinkFlasher.spec
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(os.path.abspath(SPECPATH))

datas = [(os.path.join(ROOT, "app", "targets"), "app/targets")]
binaries = []
hiddenimports = collect_submodules("pyocd")

# pyOCD 运行时按需 import 的包，静态分析抓不到，全部收进来
for pkg in ("pyocd", "hidapi", "libusb_package", "cmsis_pack_manager", "intelhex", "elftools", "usb"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # 某个包缺了不影响其它
        print("collect_all %s 失败: %s" % (pkg, e))

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DAPLinkFlasher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
