"""Native, accessible Tk desktop interface; no web server or browser required."""
from datetime import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageGrab, ImageTk
from .core import PromptMatcher
from .journal import Journal
from .ocr import OCR
from .settings import load_settings, save_settings
from .watcher import Watcher, WatchSettings

BG = "#0b1218"
PANEL = "#121e28"
BORDER = "#2a3b48"
FG = "#e6edf3"
MUTED = "#93a8b8"
ACCENT = "#68e1c5"


class RegionPicker(tk.Toplevel):
    def __init__(self, root, snapshot, callback):
        super().__init__(root)
        self.callback = callback
        self.start = None
        self.rect = None
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        self.geometry(f"{width}x{height}+0+0")
        snapshot = snapshot.resize((width, height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(snapshot)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_rectangle(0, 0, width, height, fill="black", stipple="gray50", outline="")
        self.canvas.create_rectangle(22, 22, min(width - 22, 655), 88, fill=PANEL, outline=ACCENT)
        self.canvas.create_text(40, 43, text="Drag around the console prompt area", fill=FG, anchor="w", font=("Helvetica", 16, "bold"))
        self.canvas.create_text(40, 68, text="Include the question and all choices. Escape cancels.", fill=ACCENT, anchor="w", font=("Helvetica", 11))
        self.bind("<Escape>", lambda event: self.finish(None))
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.focus_force()
        self.grab_set()

    def begin(self, event):
        self.start = (event.x, event.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=ACCENT, width=3)

    def drag(self, event):
        if self.start:
            self.canvas.coords(self.rect, *self.start, event.x, event.y)

    def release(self, event):
        if not self.start:
            return
        width, height = self.winfo_width(), self.winfo_height()
        x1, x2 = sorted((max(0, min(self.start[0], width)), max(0, min(event.x, width))))
        y1, y2 = sorted((max(0, min(self.start[1], height)), max(0, min(event.y, height))))
        if x2 - x1 >= 100 and y2 - y1 >= 50:
            self.finish((x1, y1, x2, y2))

    def finish(self, region):
        self.grab_release()
        self.destroy()
        self.callback(region)


class Console:
    """One watched terminal: a screen area, its bound window, and an on/off switch."""
    def __init__(self, number, region, enabled):
        self.id = number
        self.name = f"Console {number}"
        self.region = region
        self.target = None
        self.title = ""
        self.worker = None
        self.removed = False
        self.enabled = enabled
        self.status = tk.StringVar(value="Off")
        self.row = None
        self.switch = None
        self.label = None

    def description(self):
        x1, y1, x2, y2 = self.region
        return f"{self.name} · {self.title or 'not bound yet'} · {x2-x1}×{y2-y1} at {x1},{y1}"


class TaggedEvents:
    """Lets each console's watcher share the UI queue."""
    def __init__(self, events, console_id):
        self.events = events
        self.console_id = console_id

    def put(self, item):
        self.events.put((self.console_id,) + tuple(item))


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Console Clicker")
        height = min(860, self.root.winfo_screenheight() - 80)
        self.root.geometry(f"1080x{height}")
        self.root.minsize(900, min(660, height))
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.journal = Journal()
        self.consoles = {}
        self.next_number = 1
        self.selected = None
        self.hotkey = None
        self.count = 0
        self.preview_photo = None
        self.closing = False
        self.testing = False
        self.controls = []
        saved = load_settings()
        self.approvals = tk.BooleanVar(value=saved.get("approvals", True) is True)
        self.choices = tk.BooleanVar(value=saved.get("choices", True) is True)
        self.opencode = tk.BooleanVar(value=saved.get("opencode", True) is True)
        self.dry_run = tk.BooleanVar(value=saved.get("dry_run", False) is True)
        self.background = tk.BooleanVar(value=saved.get("background", True) is True and sys.platform != "darwin")
        self.interval = tk.StringVar(value=str(saved.get("interval", 0.5)))
        self.delay = tk.StringVar(value=str(saved.get("settle", 0.7)))
        self.idle = tk.StringVar(value=str(saved.get("idle", 5.0)))
        self.custom = tk.StringVar(value=str(saved.get("custom", "")))
        self.status = tk.StringVar(value="Ready · add a console to begin")
        self.viewing = tk.StringVar(value="RECOGNIZED TEXT")
        self.motion = tk.StringVar(value="No screen activity yet")
        self.counter = tk.StringVar(value="0")
        self._style()
        self._build()
        self.root.after(100, self.poll)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Row.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Helvetica", 11))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("Small.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 10))
        style.configure("Row.TLabel", background=BG, foreground=FG, font=("Helvetica", 10, "bold"))
        style.configure("RowSmall.TLabel", background=BG, foreground=MUTED, font=("Helvetica", 9))
        style.configure("TButton", background=BORDER, foreground=FG, borderwidth=0, padding=(16, 10), font=("Helvetica", 10, "bold"))
        style.map("TButton", background=[("active", "#3b5263"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("Small.TButton", padding=(8, 4), font=("Helvetica", 9, "bold"))
        style.configure("Accent.TButton", background=ACCENT, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#95f0db"), ("disabled", BORDER)], foreground=[("disabled", MUTED)])
        style.configure("TCheckbutton", background=PANEL, foreground=FG, font=("Helvetica", 11), padding=(0, 3))
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("Switch.TCheckbutton", background=BG, foreground=ACCENT, font=("Helvetica", 10, "bold"), padding=(0, 2))
        style.map("Switch.TCheckbutton", background=[("active", BG)], foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=BG, foreground=FG, insertcolor=FG, bordercolor=BORDER, padding=7)
        style.configure("TSpinbox", fieldbackground=BG, foreground=FG, arrowcolor=FG, bordercolor=BORDER, padding=5)

    def _build(self):
        shell = ttk.Frame(self.root, padding=(24, 16))
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x")
        ttk.Label(top, text="↵", font=("Helvetica", 34, "bold"), foreground=ACCENT).pack(side="left", padx=(0, 14))
        heading = ttk.Frame(top)
        heading.pack(side="left")
        ttk.Label(heading, text="Console Clicker", font=("Helvetica", 23, "bold")).pack(anchor="w")
        ttk.Label(heading, textvariable=self.status, foreground=ACCENT, font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(2, 0))
        ttk.Label(top, text="LOCAL / OFFLINE", foreground=ACCENT, font=("Helvetica", 9, "bold")).pack(side="right")

        # Packed before the body so they stay visible when the window is short.
        ttk.Label(shell, text="Each console binds to the terminal you focus during its 5-second countdown. Enter accepts that menu's current selection.\n"
                              "Emergency stop for all consoles: Ctrl + Alt + Q or move the pointer to the top-left screen corner.",
                  style="Muted.TLabel", font=("Helvetica", 10)).pack(side="bottom", anchor="w", pady=(10, 0))
        actions = ttk.Frame(shell)
        actions.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Button(actions, text="Add console   +", style="Accent.TButton", command=self.add_console).pack(side="left")
        self.all_off_button = ttk.Button(actions, text="All off", command=self.all_off, state="disabled")
        self.all_off_button.pack(side="left", padx=10)
        self.test_button = ttk.Button(actions, text="Test an image…", command=self.test_image)
        self.test_button.pack(side="right")
        self.controls.append(self.test_button)

        body = ttk.Frame(shell)
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=1, minsize=420)
        body.columnconfigure(1, weight=1, minsize=380)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Panel.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        ttk.Label(left, text="01   CONSOLES", style="Small.TLabel", font=("Helvetica", 10, "bold")).pack(anchor="w")
        # The console list scrolls beyond two or three rows, by screen height.
        holder = ttk.Frame(left, style="Panel.TFrame")
        holder.pack(fill="x", pady=(8, 12))
        self.visible_rows = 3
        self.list_canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, height=40)
        self.list_scroll = ttk.Scrollbar(holder, orient="vertical", command=self.list_canvas.yview)
        self.list_canvas.configure(yscrollcommand=self.list_scroll.set)
        self.list_canvas.pack(side="left", fill="x", expand=True)
        self.console_list = ttk.Frame(self.list_canvas, style="Panel.TFrame")
        window = self.list_canvas.create_window(0, 0, window=self.console_list, anchor="nw")
        self.list_canvas.bind("<Configure>", lambda event: self.list_canvas.itemconfigure(window, width=event.width))
        self.console_list.bind("<Configure>", lambda event: self.fit_list())
        holder.bind("<Enter>", lambda event: self.bind_wheel(True))
        holder.bind("<Leave>", lambda event: self.bind_wheel(False))
        self.empty_label = ttk.Label(self.console_list, text="No consoles yet. Click Add console, drag around a terminal's\nprompt area, then focus that terminal during the countdown.", style="Small.TLabel")
        self.empty_label.pack(anchor="w", pady=6)

        ttk.Label(left, text="02   PROMPT RULES", style="Small.TLabel", font=("Helvetica", 10, "bold")).pack(anchor="w")
        for text, variable in [("Command approval menus (Yes selected)", self.approvals),
                               ("Any question menu with Yes selected", self.choices),
                               ("OpenCode permission (Allow once highlighted)", self.opencode),
                               ("Test mode · detect and log without pressing", self.dry_run)]:
            widget = ttk.Checkbutton(left, text=text, variable=variable)
            widget.pack(anchor="w")
            self.controls.append(widget)
        idle_row = ttk.Frame(left, style="Panel.TFrame")
        idle_row.pack(anchor="w", fill="x")
        widget = ttk.Checkbutton(idle_row, text="Approve unfocused consoles after I'm idle for", variable=self.background)
        widget.pack(side="left")
        self.controls.append(widget)
        spin = ttk.Spinbox(idle_row, from_=2, to=120, increment=1, textvariable=self.idle, width=4)
        spin.pack(side="left", padx=6)
        self.controls.append(spin)
        ttk.Label(idle_row, text="s", style="Small.TLabel").pack(side="left")
        if sys.platform == "darwin":
            widget.configure(state="disabled")
            self.controls.remove(widget)
            ttk.Label(left, text="On macOS, a console is approved only while it is focused.", style="Small.TLabel").pack(anchor="w")
        ttk.Label(left, text="Extra pattern (optional regex; fires on any match)", style="Small.TLabel").pack(anchor="w", pady=(8, 4))
        entry = ttk.Entry(left, textvariable=self.custom)
        entry.pack(fill="x")
        self.controls.append(entry)
        timing = ttk.Frame(left, style="Panel.TFrame")
        timing.pack(fill="x", pady=(10, 0))
        for label, var in [("Poll every", self.interval), ("Confirm after", self.delay)]:
            ttk.Label(timing, text=label, style="Small.TLabel").pack(side="left")
            spin = ttk.Spinbox(timing, from_=0.2, to=10, increment=0.1, textvariable=var, width=5)
            spin.pack(side="left", padx=(6, 4))
            self.controls.append(spin)
            ttk.Label(timing, text="s", style="Small.TLabel").pack(side="left", padx=(0, 18))
        self.rules_note = ttk.Label(left, text="", style="Small.TLabel")
        self.rules_note.pack(anchor="w", pady=(6, 0))

        right = ttk.Frame(body, style="Panel.TFrame", padding=16)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(3, weight=2)
        right.rowconfigure(6, weight=1)
        right.columnconfigure(0, weight=1)
        summary = ttk.Frame(right, style="Panel.TFrame")
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(summary, textvariable=self.counter, style="Panel.TLabel", foreground=ACCENT, font=("Helvetica", 26, "bold")).pack(side="left")
        ttk.Label(summary, text=" confirmations this session", style="Small.TLabel").pack(side="left", padx=8)
        ttk.Button(summary, text="Open approval log", style="Small.TButton", command=self.open_journal).pack(side="right")
        self.preview_label = tk.Label(right, bg=BG, fg=MUTED, text="Screen preview", height=3)
        self.preview_label.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(right, textvariable=self.viewing, style="Small.TLabel", font=("Helvetica", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.text = self.text_panel(right, 3, 6)
        ttk.Label(right, textvariable=self.motion, style="Small.TLabel").grid(row=4, column=0, sticky="w", pady=(6, 10))
        ttk.Label(right, text="ACTIVITY", style="Small.TLabel", font=("Helvetica", 10, "bold")).grid(row=5, column=0, sticky="w", pady=(0, 6))
        self.log = self.text_panel(right, 6, 4)
        self.append_log(f"Approvals are logged to {self.journal.path}")

    def fit_list(self):
        rows = [console.row for console in self.consoles.values() if console.row]
        # Short screens show two consoles before the list scrolls.
        self.visible_rows = 3 if self.root.winfo_height() >= 800 else 2
        shown = rows[:self.visible_rows] if rows else [self.empty_label]
        height = sum(widget.winfo_reqheight() + 6 for widget in shown)
        self.list_canvas.configure(height=height, scrollregion=(0, 0, 0, self.console_list.winfo_reqheight()))
        if len(rows) > self.visible_rows:
            self.list_scroll.pack(side="right", fill="y")
        else:
            self.list_scroll.pack_forget()
            self.list_canvas.yview_moveto(0)

    def bind_wheel(self, active):
        def scroll(event):
            if len(self.consoles) > self.visible_rows:
                step = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
                self.list_canvas.yview_scroll(step, "units")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if active:
                self.root.bind_all(sequence, scroll)
            else:
                self.root.unbind_all(sequence)

    def text_panel(self, parent, row, height):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="nsew")
        widget = tk.Text(frame, height=height, width=30, bg=BG, fg=FG, relief="flat", padx=12, pady=10,
                         font=("Menlo" if sys.platform == "darwin" else "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 10),
                         wrap="word", state="disabled", insertbackground=ACCENT)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        widget.pack(fill="both", expand=True)
        return widget

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", datetime.now().strftime("%H:%M:%S") + "  " + text + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 300:
            self.log.delete("1.0", "2.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_text(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text or "No text recognized.")
        self.text.configure(state="disabled")

    def show_preview(self, image):
        thumbnail = image.copy()
        thumbnail.thumbnail((440, 64))
        self.preview_photo = ImageTk.PhotoImage(thumbnail)
        self.preview_label.configure(image=self.preview_photo, text="", height=64)

    def running(self):
        return [console for console in self.consoles.values() if console.worker]

    def refresh(self):
        """Rules apply to consoles as they switch on, so they lock while any is on."""
        busy = bool(self.running()) or self.testing
        for widget in self.controls:
            widget.configure(state="disabled" if busy else "normal")
        self.all_off_button.configure(state="normal" if self.running() else "disabled")
        self.rules_note.configure(text="Switch all consoles off to change rules." if self.running() else "")
        on = [console for console in self.consoles.values() if console.enabled.get()]
        if self.consoles:
            self.status.set(f"{len(on)} of {len(self.consoles)} console{'s' if len(self.consoles) != 1 else ''} on"
                            + (" · test mode" if on and self.dry_run.get() else ""))
        else:
            self.status.set("Ready · add a console to begin")
        if self.running() and not self.hotkey:
            self.start_hotkey()
        elif not self.running() and self.hotkey:
            self.hotkey.stop()
            self.hotkey = None

    # Consoles

    def add_console(self):
        self.root.withdraw()
        self.root.after(250, self.open_picker)

    def open_picker(self):
        try:
            snapshot = ImageGrab.grab()
            RegionPicker(self.root, snapshot, self.region_selected)
        except Exception as error:
            self.root.deiconify()
            messagebox.showerror("Screen capture unavailable", str(error), parent=self.root)

    def region_selected(self, region):
        self.root.deiconify()
        if not region:
            return
        console = Console(self.next_number, region, tk.BooleanVar(value=False))
        self.next_number += 1
        self.consoles[console.id] = console
        self.add_row(console)
        self.select(console)
        self.append_log(f"{console.name} added. Focus that terminal during the countdown to bind it.")
        console.enabled.set(True)
        self.toggle(console)

    def add_row(self, console):
        self.empty_label.pack_forget()
        row = ttk.Frame(self.console_list, style="Row.TFrame", padding=(10, 6))
        row.pack(fill="x", pady=3)
        console.row = row
        self.root.after_idle(self.fit_list)
        console.switch = ttk.Checkbutton(row, text="On", style="Switch.TCheckbutton", variable=console.enabled,
                                         command=lambda: self.toggle(console))
        console.switch.pack(side="left", padx=(0, 10))
        ttk.Button(row, text="✕", style="Small.TButton", width=2, command=lambda: self.remove(console)).pack(side="right")
        text = ttk.Frame(row, style="Row.TFrame")
        text.pack(side="left", fill="x", expand=True)
        console.label = ttk.Label(text, text=console.description(), style="Row.TLabel", cursor="hand2")
        console.label.pack(anchor="w")
        status = ttk.Label(text, textvariable=console.status, style="RowSmall.TLabel", cursor="hand2")
        status.pack(anchor="w")
        for widget in (row, text, console.label, status):
            widget.bind("<Button-1>", lambda event: self.select(console))

    def select(self, console):
        self.selected = console.id
        self.viewing.set(f"RECOGNIZED TEXT · {console.name.upper()}")
        for each in self.consoles.values():
            if each.label:
                each.label.configure(foreground=ACCENT if each.id == console.id else FG)

    def toggle(self, console):
        if console.enabled.get():
            self.switch_on(console)
        else:
            self.switch_off(console)
        self.refresh()

    def switch_on(self, console):
        if console.worker:
            return
        try:
            settings = self.watch_settings(console)
            matcher = self.matcher()
        except (ValueError, re.error) as error:
            console.enabled.set(False)
            messagebox.showerror("Check your settings", str(error), parent=self.root)
            return
        self.save_preferences()
        console.worker = Watcher(settings, matcher, TaggedEvents(self.events, console.id), journal=self.journal)
        console.status.set("Starting…")
        console.worker.start()

    def switch_off(self, console):
        if console.worker:
            console.worker.stop()
            console.status.set("Switching off…")
            # Re-enabled once its watcher has finished.
            console.switch.configure(state="disabled")

    def remove(self, console):
        console.removed = True
        console.enabled.set(False)
        if console.worker:
            console.worker.stop()
        else:
            self.forget(console)
        self.refresh()

    def forget(self, console):
        console.row.destroy()
        self.consoles.pop(console.id, None)
        self.root.after_idle(self.fit_list)
        if self.selected == console.id:
            self.selected = None
            self.viewing.set("RECOGNIZED TEXT")
        if not self.consoles:
            self.empty_label.pack(anchor="w", pady=6)

    def all_off(self):
        for console in self.consoles.values():
            if console.enabled.get():
                console.enabled.set(False)
                self.switch_off(console)
        self.refresh()

    def watch_settings(self, console):
        interval, delay, idle = float(self.interval.get()), float(self.delay.get()), float(self.idle.get())
        if not 0.2 <= interval <= 10 or not 0.2 <= delay <= 10:
            raise ValueError("Poll and confirm delay must be between 0.2 and 10 seconds.")
        if not 2 <= idle <= 120:
            raise ValueError("Idle time must be between 2 and 120 seconds.")
        return WatchSettings(console.region, interval=interval, settle=delay, dry_run=self.dry_run.get(),
                             name=console.name, target=console.target, title=console.title,
                             background=self.background.get(), idle=idle)

    def matcher(self):
        return PromptMatcher(self.approvals.get(), self.choices.get(), self.custom.get(), self.opencode.get())

    def save_preferences(self):
        try:
            save_settings(dict(approvals=self.approvals.get(), choices=self.choices.get(), opencode=self.opencode.get(), dry_run=self.dry_run.get(),
                               interval=float(self.interval.get()), settle=float(self.delay.get()), custom=self.custom.get(),
                               background=self.background.get(), idle=float(self.idle.get())))
        except (OSError, ValueError) as error:
            self.append_log(f"Could not save preferences: {error}")

    def start_hotkey(self):
        try:
            from pynput.keyboard import GlobalHotKeys
            def emergency():
                for console in list(self.consoles.values()):
                    if console.worker:
                        console.worker.stop()
                self.events.put((None, "log", "All consoles stopped by Ctrl + Alt + Q."))
            self.hotkey = GlobalHotKeys({"<ctrl>+<alt>+q": emergency})
            self.hotkey.start()
        except Exception as error:
            self.hotkey = None
            self.append_log(f"Global shortcut unavailable; use All off or the mouse corner. {error}")

    def open_journal(self):
        path = self.journal.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except Exception as error:
            messagebox.showinfo("Approval log", f"The approval log is at:\n{path}\n\n({error})", parent=self.root)

    def test_image(self):
        if self.running() or self.testing:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Test prompt recognition", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*")])
        if not path:
            return
        try:
            matcher = self.matcher()
        except (ValueError, re.error) as error:
            messagebox.showerror("Check your rules", str(error), parent=self.root)
            return
        self.testing = True
        self.refresh()
        self.status.set("Recognizing image locally…")
        self.viewing.set("RECOGNIZED TEXT · IMAGE TEST")
        self.selected = None
        def recognize():
            try:
                with Image.open(path) as opened:
                    image = opened.convert("RGB")
                ocr = OCR()
                text = ocr.read(image)
                match = matcher.match(text, image, ocr)
                self.events.put((None, "text", text))
                self.events.put((None, "preview", image))
                self.events.put((None, "log", "Image test: " + (f"matched {match.rule}. Would press Enter." if match else "no prompt rule matched.")))
            except Exception as error:
                self.events.put((None, "log", f"Image test failed: {error}"))
            finally:
                self.events.put((None, "test_finished", None))
        threading.Thread(target=recognize, daemon=True).start()

    def poll(self):
        try:
            while True:
                console_id, kind, value = self.events.get_nowait()
                console = self.consoles.get(console_id)
                prefix = f"{console.name}: " if console else ""
                shown = console_id == self.selected
                if kind == "status" and console:
                    if console.worker and not console.worker.stopped.is_set():
                        console.status.set(value)
                elif kind == "bound" and console:
                    console.target, console.title = value
                    console.label.configure(text=console.description())
                elif kind == "text" and shown:
                    self.show_text(value)
                elif kind == "motion" and shown:
                    self.motion.set(value)
                elif kind == "preview" and shown:
                    self.show_preview(value)
                elif kind == "log":
                    self.append_log(prefix + value)
                elif kind == "action":
                    self.count += 1
                    self.counter.set(str(self.count))
                    self.append_log(prefix + value)
                elif kind == "error" and console:
                    console.status.set("Off · " + value[:90])
                    self.append_log(prefix + value)
                elif kind == "finished" and console:
                    console.worker = None
                    if console.removed:
                        self.forget(console)
                    else:
                        console.switch.configure(state="normal")
                        if not console.status.get().startswith("Off ·"):
                            console.status.set("Off")
                        # A corner stop, hotkey or error switches the console off.
                        console.enabled.set(False)
                    self.refresh()
                    if self.closing and not self.running():
                        self.root.destroy()
                        return
                elif kind == "test_finished":
                    self.testing = False
                    self.refresh()
                    if self.closing and not self.running():
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        workers = self.running()
        for console in workers:
            console.worker.stop()
        if not workers and not self.testing:
            self.root.destroy()
        elif self.testing:
            self.status.set("Closing after recognition finishes…")
