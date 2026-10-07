"""Bundle the app with its OCR engine. Run on the target operating system."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def stage_ocr():
    executable = os.environ.get("CLICKER_TESSERACT") or shutil.which("tesseract")
    if not executable:
        raise SystemExit("Install Tesseract before building, or set CLICKER_TESSERACT to its executable.")
    executable = Path(executable).resolve()
    prefix = Path(os.environ.get("CONDA_PREFIX", sys.prefix))
    candidates = [Path(os.environ["CLICKER_TESSDATA"])] if os.environ.get("CLICKER_TESSDATA") else []
    candidates += [executable.parent / "tessdata", executable.parent.parent / "share/tessdata",
                   executable.parent.parent.parent / "share/tessdata",
                   prefix / "Library/share/tessdata", prefix / "share/tessdata",
                   Path("/usr/share/tesseract-ocr/5/tessdata"), Path("/usr/share/tesseract-ocr/4.00/tessdata"),
                   Path("/usr/share/tessdata"), Path("/opt/homebrew/share/tessdata"), Path("/usr/local/share/tessdata")]
    data = next((path for path in candidates if (path / "eng.traineddata").is_file()), None)
    if data is None:
        raise SystemExit("Cannot find eng.traineddata. Set CLICKER_TESSDATA to your Tesseract language-data directory.")
    stage = ROOT / "build/ocr"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "tessdata").mkdir(parents=True)
    shutil.copy2(executable, stage / executable.name)
    shutil.copy2(data / "eng.traineddata", stage / "tessdata/eng.traineddata")
    if sys.platform == "win32":
        # Conda-forge places Tesseract's runtime DLLs next to the executable.
        for dll in executable.parent.glob("*.dll"):
            shutil.copy2(dll, stage / dll.name)
    print(f"Bundling {executable} and {data / 'eng.traineddata'}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true", help="Also create a distributable zip/tar.gz.")
    args = parser.parse_args()
    stage_ocr()
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build/pyinstaller-cache")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "ConsoleClicker.spec"], cwd=ROOT, env=env, check=True)
    if args.archive:
        suffix = platform.system().lower() + "-" + platform.machine().lower()
        folder = "ConsoleClicker.app" if sys.platform == "darwin" else "ConsoleClicker"
        archive = shutil.make_archive(str(ROOT / "dist" / f"ConsoleClicker-{suffix}"),
                                      "zip" if sys.platform == "win32" else "gztar", ROOT / "dist", folder)
        print(f"Created {archive}")


if __name__ == "__main__":
    main()
