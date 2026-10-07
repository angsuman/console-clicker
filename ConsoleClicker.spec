# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
import re
import sys

root = Path(SPECPATH)
version = re.search(r'__version__ = "(.+?)"', (root / 'clicker' / '__init__.py').read_text()).group(1)
stage = root / 'build' / 'ocr'
name = 'tesseract.exe' if sys.platform == 'win32' else 'tesseract'
binaries = [(str(stage / name), 'ocr')]
binaries += [(str(dll), 'ocr') for dll in stage.glob('*.dll')]
datas = [(str(stage / 'tessdata' / 'eng.traineddata'), 'ocr/tessdata'),
         (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
         (str(root / 'README.md'), '.'), (str(root / 'LICENSE'), '.')]
if sys.platform == 'win32':
    hidden = ['pynput.keyboard._win32', 'pynput.mouse._win32']
elif sys.platform == 'darwin':
    hidden = ['pynput.keyboard._darwin', 'pynput.mouse._darwin', 'AppKit', 'Quartz']
else:
    hidden = ['pynput.keyboard._xorg', 'pynput.mouse._xorg', 'Xlib.display']

a = Analysis([str(root / 'launcher.py')], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hidden,
             excludes=['numpy', 'scipy', 'pandas', 'matplotlib', 'IPython', 'pytest', 'torch', 'cv2', 'PIL.ImageQt'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ConsoleClicker', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False,
          console=(sys.platform.startswith('linux')))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ConsoleClicker')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='ConsoleClicker.app', bundle_identifier='com.consoleclicker.desktop',
                 info_plist={'NSHighResolutionCapable': True,
                             'NSHumanReadableCopyright': 'Copyright (c) 2026 Angsuman Chakraborty',
                             'NSAppleEventsUsageDescription': 'Console Clicker watches your selected terminal.',
                             'CFBundleShortVersionString': version})
