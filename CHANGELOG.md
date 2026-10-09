# Changelog

## 1.1.1

- Fix packaged screen previews by including Pillow's dynamically imported Tk
  helper on Linux, Windows and macOS.
- Add Docker smoke tests for bundled OCR, application startup, screen capture,
  prompt approval, approval logging and the emergency stop on Linux X11.
- Publish GitHub releases with Linux x64, Windows x64, macOS Apple Silicon and
  macOS Intel downloads after all platform builds and checks succeed.
- Add issue forms for bug reports and prompts that are not recognized.

## 1.1.0

- Watch several terminals at once, each with its own On switch; **All off** and
  the emergency stops cover every console.
- Approve unfocused consoles after you have been idle: the app switches to the
  terminal, re-reads the prompt, presses Enter and switches back (X11 and
  Windows).
- Append-only approval log with the time, console, rule and the recognized
  prompt text; **Open approval log** button.
- Built-in rules fire only when the menu cursor is on a **Yes** option of the
  latest question. Numbered lists in AI replies and older menus are ignored.
- OpenCode permission prompts: Enter is pressed only when **Allow once** is the
  highlighted button.
- A different prompt that replaces a handled one is answered without waiting.
- Box borders around prompts no longer prevent recognition.
- Layout fits 768-pixel-high screens; the console list scrolls.

## 1.0.0

- First version: one watched console area, offline OCR, command approval and
  numbered choice rules, test mode, emergency stops.
