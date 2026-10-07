"""Background screen watcher. Sends events to a thread-safe UI queue."""
from dataclasses import dataclass
import threading
import time
from PIL import ImageChops, ImageGrab, ImageStat
from .core import PromptGate
from .desktop import INPUT_LOCK, Desktop
from .ocr import OCR


@dataclass(frozen=True)
class WatchSettings:
    region: tuple
    interval: float = 0.5
    settle: float = 0.7
    cooldown: float = 2.0
    dry_run: bool = False
    countdown: int = 5
    name: str = "Console"
    # A window bound earlier (from a "bound" event) skips the countdown.
    target: tuple = None
    title: str = ""
    # Approve while another window is focused: switch to this console after the
    # person has used neither keyboard nor mouse for `idle` seconds.
    background: bool = False
    idle: float = 5.0
    # Seconds without keyboard or mouse input before Enter goes to a focused console.
    focused_idle: float = 1.0


def changed(previous, current, threshold=0.5):
    if previous is None:
        return True
    return ImageStat.Stat(ImageChops.difference(previous, current)).mean[0] > threshold


class Watcher(threading.Thread):
    def __init__(self, settings, matcher, events, *, desktop_factory=Desktop,
                 ocr_factory=OCR, capture=ImageGrab.grab, journal=None):
        super().__init__(name="console-watcher", daemon=True)
        self.settings = settings
        self.matcher = matcher
        self.events = events
        self.stopped = threading.Event()
        self.desktop_factory = desktop_factory
        self.ocr_factory = ocr_factory
        self.capture = capture
        self.journal = journal
        self.retry_after = float("-inf")
        self.title = settings.title

    def emit(self, kind, value):
        self.events.put((kind, value))

    def stop(self):
        self.stopped.set()

    def run(self):
        desktop = None
        try:
            self.emit("status", "Preparing local text recognition…")
            ocr = self.ocr_factory()
            desktop = self.desktop_factory()
            target, title = self.settings.target, self.settings.title
            if not target:
                for seconds in range(self.settings.countdown, 0, -1):
                    self.emit("status", f"Focus this terminal · binding in {seconds}s")
                    if self.stopped.wait(1):
                        return
                if self.stopped.is_set():
                    return
                target, title = desktop.foreground()
                if not target or desktop.own_foreground(target) or title == "Console Clicker":
                    raise RuntimeError("Focus the terminal during the countdown, then switch it on again.")
                self.emit("bound", (target, title))
            self.title = title
            self.emit("target", title)
            background = self.settings.background and getattr(desktop, "can_activate", False)
            self.emit("log", f"Watching {title}. " + ("Test mode: keys are disabled." if self.settings.dry_run else "Enter confirms the current selection.")
                      + (" Approves in the background when you are idle." if background else ""))
            gate = PromptGate(settle=self.settings.settle, cooldown=self.settings.cooldown)
            previous = None
            last_ocr = float("-inf")
            was_watching = False
            while not self.stopped.is_set():
                if desktop.corner_stop():
                    self.emit("log", "Stopped by mouse corner emergency stop.")
                    self.stop()
                    break
                focused = desktop.foreground()[0] == target
                if not focused and not background:
                    self.emit("status", "Waiting · focus this terminal to resume")
                    # Never read an overlapping window as a cleared console prompt.
                    was_watching = False
                    if self.stopped.wait(self.settings.interval):
                        break
                    continue
                image = self.capture(bbox=self.settings.region).convert("RGB")
                thumb = image.convert("L").resize((160, 80))
                now = time.monotonic()
                motion = changed(previous, thumb)
                previous = thumb
                # Recheck static screens so stable prompts are recognized twice;
                # cursor blinking need not trigger a full OCR on every frame.
                if not was_watching or motion or now - last_ocr >= 1.0:
                    text = ocr.read(image)
                    last_ocr = time.monotonic()
                    if self.stopped.is_set():
                        break
                    # Ignore stale OCR if the user changed applications mid-read.
                    if not background and desktop.foreground()[0] != target:
                        was_watching = False
                        continue
                    match = self.matcher.match(text, image, ocr)
                    self.emit("text", text)
                    self.emit("motion", "Text moved" if motion else "Screen steady")
                    self.emit("preview", image.copy())
                    ready = gate.observe(match, last_ocr) and last_ocr >= self.retry_after
                    if ready:
                        # OCR can take time. Confirm the captured prompt is still on screen.
                        fresh = self.capture(bbox=self.settings.region).convert("RGB")
                        fresh_thumb = fresh.convert("L").resize((160, 80))
                        if changed(thumb, fresh_thumb, threshold=1.5):
                            self.emit("status", "Text changed during recognition · checking again")
                            previous = None
                            was_watching = False
                            continue
                        if self.stopped.is_set():
                            break
                        delivered = self.deliver(desktop, ocr, target, match, background)
                        if delivered:
                            gate.mark_fired(time.monotonic())
                            self.record(match, text)
                            self.emit("action", ("Would press Enter" if self.settings.dry_run else "Pressed Enter") + f" · {match.rule}")
                    if gate.latched:
                        self.emit("status", "Prompt handled · waiting for it to disappear")
                    elif match and not ready:
                        self.emit("status", f"Detected {match.rule.lower()} · checking stability")
                    elif not match:
                        self.emit("status", "Watching · waiting for a choice prompt")
                was_watching = True
                if self.stopped.wait(self.settings.interval):
                    break
        except Exception as error:
            self.emit("error", str(error))
        finally:
            try:
                if desktop:
                    desktop.close()
            finally:
                self.emit("finished", None)

    def record(self, match, text):
        if not self.journal:
            return
        try:
            self.journal.record(f"{self.settings.name} · {self.title or 'terminal'}", match.rule, text, self.settings.dry_run)
        except OSError as error:
            self.emit("log", f"Could not write the approval log: {error}")

    def idle_enough(self, desktop, seconds):
        idle = desktop.idle_seconds() if hasattr(desktop, "idle_seconds") else None
        return idle is None or idle >= seconds

    def deliver(self, desktop, ocr, target, match, background):
        """Press Enter in the console, switching focus to it and back when allowed."""
        if self.settings.dry_run:
            return background or desktop.foreground()[0] == target
        with INPUT_LOCK:
            if self.stopped.is_set() or desktop.corner_stop():
                return False
            previous = desktop.foreground()[0]
            if previous == target:
                # Do not race keystrokes the person is typing into this console.
                if not self.idle_enough(desktop, self.settings.focused_idle):
                    self.emit("status", f"Detected {match.rule.lower()} · waiting for typing to pause")
                    return False
                return desktop.press_enter(target, self.stopped)
            if not background:
                return False
            idle = desktop.idle_seconds()
            if idle is None or idle < self.settings.idle:
                self.emit("status", f"Detected {match.rule.lower()} · will approve after {self.settings.idle:g}s without input")
                return False
            started = time.monotonic()
            if not desktop.activate(target):
                return self.abandon("could not switch to this console")
            try:
                if self.stopped.wait(0.35) or desktop.foreground()[0] != target:
                    return self.abandon("the window manager did not focus this console")
                # The console is now on top; read it again so a window that
                # covered the area cannot cause an approval.
                image = self.capture(bbox=self.settings.region).convert("RGB")
                check = self.matcher.match(ocr.read(image), image, ocr)
                if not check or check.rule != match.rule:
                    return self.abandon("the prompt was not visible once the console was focused")
                idle = desktop.idle_seconds()
                if idle is not None and idle < time.monotonic() - started:
                    return self.abandon("you used the keyboard or mouse while switching")
                return desktop.press_enter(target, self.stopped)
            finally:
                if previous:
                    self.stopped.wait(0.1)
                    desktop.activate(previous)

    def abandon(self, reason):
        self.retry_after = time.monotonic() + 10
        self.emit("log", f"Skipped a background approval: {reason}. Retrying in 10s.")
        return False
