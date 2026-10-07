import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Console Clicker — watch terminal prompts and press Enter.")
    parser.add_argument("--check-image", metavar="PATH", help="Recognize an image without a desktop or key presses; outputs JSON.")
    parser.add_argument("--demo", action="store_true", help="Open a harmless console-style prompt for testing.")
    args = parser.parse_args()
    if args.check_image:
        from PIL import Image
        from clicker.core import PromptMatcher
        from clicker.ocr import OCR
        try:
            ocr = OCR()
            with Image.open(args.check_image) as opened:
                image = opened.convert("RGB")
            text = ocr.read(image)
            match = PromptMatcher().match(text, image, ocr)
            print(json.dumps({"text": text, "matched": bool(match), "rule": match.rule if match else None}, indent=2))
            return 0 if match else 2
        except Exception as error:
            print(json.dumps({"error": str(error)}), file=sys.stderr)
            return 1
    from clicker.desktop import enable_dpi_awareness
    enable_dpi_awareness()
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"A graphical desktop is required: {error}", file=sys.stderr)
        return 1
    if args.demo:
        from clicker.demo import Demo
        Demo(root)
    else:
        from clicker.ui import App
        App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
