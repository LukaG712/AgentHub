# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['hub/cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('hub/static', 'hub/static'),
        ('hub.example.yaml', '.'),
    ],
    hiddenimports=[
        'hub',
        'hub.agents',
        'hub.api',
        'hub.config',
        'hub.coordinator',
        'hub.git_service',
        'hub.memory',
        'hub.obsidian',
        'hub.ollama',
        'hub.providers',
        'hub.remote',
        'hub.runner',
        'hub.skills',
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
    name='agent-hub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='agent-hub',
)
