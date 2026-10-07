Console Clicker bundles third-party software. Its MIT license does not replace
the licenses of those components. PyInstaller's dependency analysis includes
the shared libraries required by the builder's Tesseract and Python binaries;
their exact versions vary with the build platform.

- Python and Tk/Tcl: PSF and Tcl/Tk licenses. https://docs.python.org/3/license.html and https://www.tcl.tk/software/tcltk/license.html
- Pillow: HPND license. https://github.com/python-pillow/Pillow/blob/main/LICENSE
- pynput: LGPL-3.0. https://github.com/moses-palmer/pynput/blob/master/COPYING.LGPL
- python-xlib (Linux): LGPL-2.1. https://github.com/python-xlib/python-xlib/blob/master/LICENSE
- PyObjC (macOS): MIT. https://github.com/ronaldoussoren/pyobjc/blob/master/pyobjc-core/LICENSE.txt
- Tesseract executable and English trained data: Apache-2.0. https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE and https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE
- Leptonica: BSD-2-Clause. https://github.com/DanBloomberg/leptonica/blob/master/leptonica-license.txt
- PyInstaller: GPL with an exception for distributing bundled applications. https://pyinstaller.org/en/stable/license.html

Redistributors should retain the license files supplied with their platform's
runtime dependencies and comply with their redistribution terms. Build outputs
include this notice; package metadata collected by PyInstaller may also carry
upstream licenses. The corresponding upstream source is available at the links
above. Linux executables rely on the host's glibc and X11 desktop.
