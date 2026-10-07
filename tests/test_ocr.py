from pathlib import Path
import os
import shutil
from PIL import Image
import pytest
from clicker.core import PromptMatcher
from clicker.ocr import OCR


def test_prepare_preserves_colored_terminal_text():
    image = Image.new("RGB", (150, 60), "black")
    image.putpixel((50, 30), (0, 0, 255))
    result = OCR.prepare(image)
    assert result.mode == "L"
    assert result.getpixel((0, 0)) == 255
    assert result.getpixel((116, 76)) < 200


@pytest.mark.skipif(not (shutil.which("tesseract") or os.environ.get("CLICKER_TESSERACT")), reason="Tesseract not installed")
@pytest.mark.parametrize("name", ["approval", "approval_boxed"])
def test_actual_screenshot_with_real_offline_ocr(name):
    # Rendered in xterm with a ❯ cursor; the boxed one has │ borders OCR reads as "|".
    with Image.open(Path(__file__).parent / f"fixtures/{name}.png") as image:
        text = OCR().read(image)
    assert "?" in text
    assert PromptMatcher().match(text).rule == "Command approval"


@pytest.mark.skipif(not (shutil.which("tesseract") or os.environ.get("CLICKER_TESSERACT")), reason="Tesseract not installed")
@pytest.mark.parametrize("name, fires", [("opencode_once", True), ("opencode_always", False), ("opencode_reject", False)])
def test_real_opencode_screens(name, fires):
    # Captured from OpenCode 1.18.35 in xterm; only the highlight color marks the selection.
    ocr = OCR()
    with Image.open(Path(__file__).parent / f"fixtures/{name}.png") as opened:
        image = opened.convert("RGB")
    match = PromptMatcher().match(ocr.read(image), image, ocr)
    assert (match is not None and match.rule == "OpenCode permission") is fires
