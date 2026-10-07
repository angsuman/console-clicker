"""Native foreground identity and input. Imports are lazy for headless tests."""
import ctypes
import os
import sys
import threading
import time

# Watchers of different consoles share the keyboard; one switches focus and
# presses Enter at a time.
INPUT_LOCK = threading.Lock()


class UserActivity:
    """Seconds since the person last used the keyboard or mouse, from pynput listeners."""
    def __init__(self):
        self.last = time.monotonic()
        self.listeners = []
        self.available = False

    def touch(self, *args):
        self.last = time.monotonic()

    def start(self):
        if self.listeners:
            return
        try:
            from pynput import keyboard, mouse
            self.listeners = [keyboard.Listener(on_press=self.touch, on_release=self.touch),
                              mouse.Listener(on_move=self.touch, on_click=self.touch, on_scroll=self.touch)]
            for listener in self.listeners:
                listener.daemon = True
                listener.start()
            self.available = True
        except Exception:
            self.available = False

    def idle(self):
        return time.monotonic() - self.last if self.available else None


_activity = UserActivity()


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


class Desktop:
    def __init__(self):
        if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            raise RuntimeError("Use an X11 desktop session for console watching. Native Wayland input is not supported.")
        from pynput import keyboard, mouse
        self.keyboard = keyboard
        self.keys = keyboard.Controller()
        self.mouse = mouse.Controller()
        self.display = None
        if sys.platform.startswith("linux"):
            from Xlib import display
            self.display = display.Display()
        elif sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.GetForegroundWindow.restype = ctypes.c_void_p
            self.user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
            self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            self.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            self.user32.IsIconic.argtypes = [ctypes.c_void_p]
            self.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        elif sys.platform == "darwin":
            from AppKit import NSWorkspace
            self.workspace = NSWorkspace.sharedWorkspace()
        # macOS activates applications, not one of an application's windows, so
        # background consoles there are approved only when focused.
        self.can_activate = sys.platform != "darwin"
        _activity.start()

    def idle_seconds(self):
        return _activity.idle()

    def activate(self, target):
        """Ask the window manager to focus a window; callers verify with foreground()."""
        if not target or not target[0]:
            return False
        try:
            if sys.platform == "win32":
                handle = target[0]
                kernel32 = ctypes.WinDLL("kernel32")
                current = self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), None)
                own = kernel32.GetCurrentThreadId()
                # Windows allows focus changes from the thread that owns current input.
                attached = current != own and self.user32.AttachThreadInput(own, current, True)
                try:
                    if self.user32.IsIconic(handle):
                        self.user32.ShowWindow(handle, 9)
                    return bool(self.user32.SetForegroundWindow(handle))
                finally:
                    if attached:
                        self.user32.AttachThreadInput(own, current, False)
            if sys.platform.startswith("linux"):
                from Xlib import X
                from Xlib.protocol import event
                root = self.display.screen().root
                window = self.display.create_resource_object("window", target[0])
                # Source 2 marks a pager-style request, which window managers honor.
                message = event.ClientMessage(window=window, client_type=self.display.intern_atom("_NET_ACTIVE_WINDOW"),
                                              data=(32, [2, X.CurrentTime, 0, 0, 0]))
                root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                self.display.flush()
                return True
        except Exception:
            return False
        return False

    def foreground(self):
        if sys.platform == "win32":
            handle = self.user32.GetForegroundWindow()
            title = ctypes.create_unicode_buffer(512)
            self.user32.GetWindowTextW(handle, title, len(title))
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            return (handle, pid.value), title.value or "Untitled window"
        if sys.platform == "darwin":
            # App identity is used on macOS; Quartz also distinguishes its windows.
            import Quartz
            app = self.workspace.frontmostApplication()
            pid = app.processIdentifier()
            windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
            for window in windows:
                if window.get(Quartz.kCGWindowOwnerPID) == pid and window.get(Quartz.kCGWindowLayer) == 0:
                    return (pid, int(window[Quartz.kCGWindowNumber])), app.localizedName()
            return (pid, 0), app.localizedName()
        root = self.display.screen().root
        active = root.get_full_property(self.display.intern_atom("_NET_ACTIVE_WINDOW"), 0)
        if active is None or not len(active.value) or not active.value[0]:
            # Some lightweight X11 window managers only expose input focus.
            window = self.display.get_input_focus().focus
            if not hasattr(window, "id"):
                return None, "No focused window"
        else:
            window = self.display.create_resource_object("window", int(active.value[0]))
        prop = window.get_full_property(self.display.intern_atom("_NET_WM_NAME"), 0)
        title = prop.value.decode("utf-8", errors="replace") if prop and isinstance(prop.value, bytes) else window.get_wm_name()
        pid_prop = window.get_full_property(self.display.intern_atom("_NET_WM_PID"), 0)
        pid = int(pid_prop.value[0]) if pid_prop is not None and len(pid_prop.value) else 0
        return (window.id, pid), title or "X11 window"

    def own_foreground(self, target):
        if not target:
            return True
        return target[0] == os.getpid() if sys.platform == "darwin" else target[1] == os.getpid()

    def corner_stop(self):
        x, y = self.mouse.position
        return 0 <= x <= 3 and 0 <= y <= 3

    def press_enter(self, target, stopped):
        # The check is adjacent to key delivery to minimize focus races.
        if stopped.is_set() or self.corner_stop() or self.foreground()[0] != target:
            return False
        try:
            self.keys.press(self.keyboard.Key.enter)
        finally:
            self.keys.release(self.keyboard.Key.enter)
        return True

    def close(self):
        if self.display:
            self.display.close()
