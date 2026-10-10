# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['opendisplay_server.py'],
    pathex=[],
    binaries=[('app_win/adb.exe', '.'), ('app_win/AdbWinApi.dll', '.'), ('app_win/AdbWinUsbApi.dll', '.'), ('server/driver/vdd_bin/VirtualDisplayDriver/devcon.exe', '.')],
    datas=[('app_icon.ico', '.'), ('app_icon.png', '.'), ('server/driver/aoap_bin/opendisplay_aoap.inf', '.')],
    hiddenimports=['server.autostart', 'dxcam', 'comtypes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenDisplay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OpenDisplay',
)
