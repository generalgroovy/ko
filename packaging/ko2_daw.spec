# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path.cwd()

block_cipher = None


a = Analysis(
    [str(ROOT / "packaging" / "ko2_daw_runtime.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "README.md"), "."),
    ],
    hiddenimports=[
        "ko2_daw.app",
        "ko2_daw.launcher",
        "ko2_daw.gui",
        "ko2_daw.gui_all_groups_matrix",
        "ko2_daw.gui_comm_panel",
        "ko2_daw.gui_connection_guard",
        "ko2_daw.gui_detection_menu",
        "ko2_daw.gui_device_main",
        "ko2_daw.gui_file_explorer_window",
        "ko2_daw.gui_midi_detection",
        "ko2_daw.gui_protocol_window",
        "ko2_daw.gui_scrollbars",
        "ko2_daw.gui_song_timeline",
        "ko2_daw.gui_state_poll",
        "ko2_daw.hardware_explorer",
        "tkinter",
        "tkinter.ttk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KO2-DAW",
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KO2-DAW",
)
