"""Offline OCR with a bundled Tesseract executable and English model."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from PIL import Image, ImageOps, ImageStat


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def subprocess_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class OCR:
    def __init__(self):
        root = resource_root()
        name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
        bundled = root / "ocr" / name
        self.executable = str(bundled) if bundled.is_file() else os.environ.get("CLICKER_TESSERACT") or shutil.which(name)
        if not self.executable:
            raise RuntimeError("Tesseract is missing. Use the packaged app, or install Tesseract with English language data.")
        data = root / "ocr" / "tessdata"
        if not bundled.is_file() and os.environ.get("CLICKER_TESSDATA"):
            data = Path(os.environ["CLICKER_TESSDATA"])
        self.data = data if (data / "eng.traineddata").exists() else None
        self.env = os.environ.copy()
        self.env["OMP_THREAD_LIMIT"] = "1"
        # Windows subprocess DLL search does not inherit AddDllDirectory handles.
        if bundled.is_file():
            self.env["PATH"] = os.pathsep.join((str(root / "ocr"), str(root), self.env.get("PATH", "")))
        elif sys.platform == "win32":
            self.env["PATH"] = os.pathsep.join((str(Path(self.executable).parent), self.env.get("PATH", "")))

    @staticmethod
    def prepare(image):
        # A channel maximum preserves blue/green terminal selections on black.
        rgb = image.convert("RGB")
        from PIL import ImageChops
        channels = rgb.split()
        gray = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        if ImageStat.Stat(gray).mean[0] < 125:
            gray = ImageOps.invert(gray)
        gray = ImageOps.autocontrast(gray)
        # Screen fonts recognize better around 30–40 pixels high.
        if gray.width <= 2600:
            gray = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
        return ImageOps.expand(gray, border=16, fill="white")

    def read(self, image):
        buffer = io.BytesIO()
        self.prepare(image).save(buffer, format="PNG")
        args = [self.executable, "stdin", "stdout", "-l", "eng", "--psm", "6"]
        if self.data:
            args += ["--tessdata-dir", str(self.data)]
        result = subprocess.run(args, input=buffer.getvalue(), capture_output=True,
                                env=self.env, timeout=10, **subprocess_options())
        if result.returncode:
            raise RuntimeError("OCR failed: " + result.stderr.decode("utf-8", errors="replace")[-700:])
        return result.stdout.decode("utf-8", errors="replace").strip()
