import queue
import threading
from PIL import Image
from clicker.core import PromptMatcher
from clicker.watcher import Watcher, WatchSettings, changed


PROMPT = "Run this command?\n> 1. Yes, run command\n2. No, cancel"


class FakeDesktop:
    def __init__(self):
        self.target = (10, 20)
        self.presses = 0
        self.corner = False
        self.closed = False

    def foreground(self):
        return self.target, "Test console"

    def own_foreground(self, target):
        return False

    def corner_stop(self):
        return self.corner

    def press_enter(self, target, stopped):
        if stopped.is_set() or target != self.target:
            return False
        self.presses += 1
        return True

    def close(self):
        self.closed = True


class FakeOCR:
    def __init__(self, callback=None):
        self.reads = 0
        self.callback = callback

    def read(self, image):
        self.reads += 1
        if self.callback:
            self.callback(self.reads)
        return PROMPT


def launch(desktop, ocr, dry=False, capture=None):
    events = queue.Queue()
    frames = [Image.new("RGB", (160, 80), "black"), Image.new("RGB", (160, 80), "white")]
    captures = [0]
    def moving_capture(**kwargs):
        captures[0] += 1
        # Each main frame moves, but its immediate pre-delivery check is unchanged.
        return frames[(captures[0] - 1) % 2]
    settings = WatchSettings((0, 0, 160, 80), interval=0.01, settle=0, countdown=0, dry_run=dry)
    worker = Watcher(settings, PromptMatcher(), events, desktop_factory=lambda: desktop,
                     ocr_factory=lambda: ocr, capture=capture or moving_capture)
    return worker, events


def consume_until(events, kind, timeout=4):
    import time
    deadline = time.monotonic() + timeout
    collected = []
    while time.monotonic() < deadline:
        item = events.get(timeout=max(0.01, deadline - time.monotonic()))
        collected.append(item)
        if item[0] == kind:
            return collected
    raise AssertionError(f"No {kind} event: {collected}")


def test_watcher_delivers_once_then_latches():
    desktop = FakeDesktop()
    ocr = FakeOCR()
    image = Image.new("RGB", (160, 80), "black")
    worker, events = launch(desktop, ocr, capture=lambda **kwargs: image)
    worker.start()
    try:
        consume_until(events, "action")
        assert desktop.presses == 1
        # A further complete OCR must not produce another key.
        consume_until(events, "text")
        consume_until(events, "status")
        assert desktop.presses == 1
    finally:
        worker.stop()
        worker.join(2)
    assert desktop.closed
    assert not worker.is_alive()


def test_dry_run_logs_without_keys():
    desktop = FakeDesktop()
    worker, events = launch(desktop, FakeOCR(), dry=True, capture=lambda **kwargs: Image.new("RGB", (160, 80)))
    worker.start()
    try:
        collected = consume_until(events, "action")
        assert "Would press Enter" in collected[-1][1]
        assert desktop.presses == 0
    finally:
        worker.stop()
        worker.join(2)


def test_focus_change_during_ocr_prevents_key():
    desktop = FakeDesktop()
    ocr = FakeOCR(lambda reads: setattr(desktop, "target", (99, 99)))
    worker, events = launch(desktop, ocr)
    worker.start()
    try:
        consume_until(events, "status")
        # Wait for the explicit focus-wait status following OCR.
        while True:
            item = events.get(timeout=2)
            if item[0] == "status" and "focus this terminal" in item[1]:
                break
        assert desktop.presses == 0
    finally:
        worker.stop()
        worker.join(2)


def test_stop_during_ocr_prevents_key():
    desktop = FakeDesktop()
    ocr = FakeOCR()
    worker, events = launch(desktop, ocr)
    ocr.callback = lambda reads: worker.stop()
    worker.start()
    consume_until(events, "finished")
    worker.join(2)
    assert desktop.presses == 0


def test_changing_screen_before_delivery_prevents_key():
    desktop = FakeDesktop()
    worker, events = launch(desktop, FakeOCR())
    worker.start()
    try:
        while True:
            item = events.get(timeout=2)
            if item[0] == "status" and "changed during" in item[1]:
                break
        assert desktop.presses == 0
    finally:
        worker.stop()
        worker.join(2)


def test_corner_emergency_stop():
    desktop = FakeDesktop()
    desktop.corner = True
    worker, events = launch(desktop, FakeOCR())
    worker.start()
    collected = consume_until(events, "finished")
    worker.join(2)
    assert any(kind == "log" and "emergency" in value for kind, value in collected)
    assert desktop.presses == 0


def test_motion_threshold():
    a = Image.new("L", (160, 80), 0)
    b = Image.new("L", (160, 80), 255)
    assert changed(None, a)
    assert changed(a, b)
    assert not changed(a, a.copy())


def test_ocr_failure_stops_cleanly():
    desktop = FakeDesktop()
    class BrokenOCR:
        def read(self, image):
            raise RuntimeError("OCR failed")
    worker, events = launch(desktop, BrokenOCR())
    worker.start()
    collected = consume_until(events, "finished")
    worker.join(2)
    assert ("error", "OCR failed") in collected
    assert desktop.closed
    assert desktop.presses == 0


class BackgroundDesktop(FakeDesktop):
    """The console is bound but another window has focus until activated."""
    def __init__(self, idle=60):
        super().__init__()
        self.focused = (1, 1)
        self.idle = idle
        self.can_activate = True
        self.activations = []

    def foreground(self):
        return self.focused, "Other window"

    def idle_seconds(self):
        return self.idle

    def activate(self, target):
        self.activations.append(target)
        self.focused = target
        return True

    def press_enter(self, target, stopped):
        if stopped.is_set() or self.focused != target:
            return False
        self.presses += 1
        return True


class RecordingJournal:
    def __init__(self):
        self.entries = []

    def record(self, console, rule, text, dry_run=False):
        self.entries.append((console, rule, text, dry_run))


def launch_background(desktop, ocr, journal=None):
    events = queue.Queue()
    image = Image.new("RGB", (160, 80), "black")
    settings = WatchSettings((0, 0, 160, 80), interval=0.01, settle=0, countdown=0, name="Console 2",
                             target=(10, 20), title="Bound console", background=True, idle=5)
    worker = Watcher(settings, PromptMatcher(), events, desktop_factory=lambda: desktop,
                     ocr_factory=lambda: ocr, capture=lambda **kwargs: image, journal=journal)
    return worker, events


def test_background_console_is_focused_approved_and_focus_restored():
    desktop = BackgroundDesktop()
    journal = RecordingJournal()
    worker, events = launch_background(desktop, FakeOCR(), journal)
    worker.start()
    try:
        collected = consume_until(events, "action")
        assert not any(kind == "bound" for kind, _ in collected)
        assert desktop.presses == 1
        assert desktop.activations == [(10, 20), (1, 1)]
        assert desktop.focused == (1, 1)
        assert journal.entries == [("Console 2 · Bound console", "Command approval", PROMPT, False)]
    finally:
        worker.stop()
        worker.join(2)


def test_background_console_waits_while_the_person_is_active():
    desktop = BackgroundDesktop(idle=1)
    worker, events = launch_background(desktop, FakeOCR())
    worker.start()
    try:
        while True:
            kind, value = events.get(timeout=2)
            if kind == "status" and "without input" in value:
                break
        assert desktop.presses == 0
        assert desktop.activations == []
    finally:
        worker.stop()
        worker.join(2)


def test_background_approval_is_abandoned_when_prompt_is_not_on_the_focused_console():
    desktop = BackgroundDesktop()
    ocr = FakeOCR()
    # Before switching, a covering window shows a prompt; the console itself does not.
    original = ocr.read
    ocr.read = lambda image: original(image) if desktop.focused != (10, 20) else "$ "
    worker, events = launch_background(desktop, ocr)
    worker.start()
    try:
        collected = consume_until(events, "log")
        while not (collected[-1][0] == "log" and "Skipped" in collected[-1][1]):
            collected = consume_until(events, "log")
    finally:
        worker.stop()
        worker.join(2)
    assert desktop.presses == 0
    assert desktop.focused == (1, 1)


def test_countdown_binding_is_reported_for_reuse():
    desktop = FakeDesktop()
    worker, events = launch(desktop, FakeOCR(), dry=True, capture=lambda **kwargs: Image.new("RGB", (160, 80)))
    worker.start()
    try:
        collected = consume_until(events, "bound")
        assert collected[-1][1] == ((10, 20), "Test console")
    finally:
        worker.stop()
        worker.join(2)
