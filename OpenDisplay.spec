# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['opendisplay_server.py'],
    pathex=[],
    binaries=[
        ('app_win/adb.exe', '.'),
        ('app_win/AdbWinApi.dll', '.'),
        ('app_win/AdbWinUsbApi.dll', '.'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/devcon.exe', 'driver'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/MttVDD.dll', 'driver'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/mttvdd.cat', 'driver'),
    ],
    datas=[
        ('app_icon.ico', '.'),
        ('server/driver/aoap_bin/opendisplay_aoap.inf', 'driver'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/MttVDD.inf', 'driver'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/Virtual_Display_Driver.cer', 'driver'),
        ('server/driver/vdd_bin/VirtualDisplayDriver/vdd_settings.xml', 'driver'),
    ],
    hiddenimports=['server.autostart', 'dxcam', 'comtypes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'tensorflow', 'keras', 'playwright', 'selenium',
        'xgboost', 'scipy', 'matplotlib', 'pandas', 'seaborn',
        'onnxruntime', 'chromadb', 'IPython', 'ipykernel', 'jupyter',
        'nltk', 'gensim', 'mediapipe', 'h5py', 'pyarrow',
        'transformers', 'tokenizers', 'llama_index', 'langchain',
        'pytest', 'libclang', 'flatbuffers', 'jax', 'tensorboard'
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OpenDisplay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
