"""Prompt rules and once-per-prompt state; independent of desktop APIs."""
from dataclasses import dataclass
import re
import unicodedata


# Box and panel borders that OCR reads at line edges, usually as "|".
BORDER = re.compile(r"^[|│┃║¦]+|[|│┃║¦]+$")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(BORDER.sub("", line).strip() for line in lines)


@dataclass(frozen=True)
class Match:
    rule: str
    evidence: str
    # Identifies one prompt (its question and the command above it), so a
    # different prompt that replaces a handled one is answered without a gap.
    key: str = ""


class PromptMatcher:
    def __init__(self, approvals=True, choices=True, custom="", opencode=True):
        self.approvals = approvals
        self.choices = choices
        self.opencode = opencode
        # A custom expression is an additional rule. Empty expressions are ignored.
        self.custom = re.compile(custom, re.IGNORECASE | re.MULTILINE) if custom.strip() else None
        if self.custom and self.custom.search(""):
            raise ValueError("The custom rule must not match empty text.")
        if not (approvals or choices or opencode or self.custom):
            raise ValueError("Enable at least one prompt rule.")

    def match(self, text: str, image=None, ocr=None):
        """Match recognized text. The OpenCode rule also needs the screen image
        and OCR engine, because its selected option is shown only by color."""
        normalized = normalize(text)
        # Built-in rules judge only the latest question with a numbered menu, and
        # fire only when its cursor line says Yes. Numbered lists in an AI reply
        # have no cursor; older menus above a newer question are ignored.
        question, tail, context = latest_menu(normalized)
        if question and selected_yes(tail):
            if self.approvals and APPROVAL_QUESTION.search(question):
                return Match("Command approval", question, context)
            if self.choices:
                return Match("Choice menu", question, context)
        if self.opencode and image is not None and ocr is not None:
            header = list(OPENCODE_PROMPT.finditer(normalized))
            buttons = OPENCODE_BUTTONS.search(normalized, header[-1].end()) if header else None
            if buttons and opencode_selected(image, ocr) == "allow once":
                request = normalized[header[-1].end():buttons.start()]
                return Match("OpenCode permission", "permission required · allow once", "opencode\n" + request)
        if self.custom:
            result = self.custom.search(text)
            if result and result.group().strip():
                return Match("Custom rule", result.group().strip()[:180])
        return None


APPROVAL_QUESTION = re.compile(r"(?:run\s+this\s+command|do\s+you\s+want\s+to\s+(?:proceed|continue)|allow\s+this\s+(?:command|action))\s*\?")
QUESTION = re.compile(r"(?:[^\n]{0,160}\?|(?:select|choose)\s+(?:an?\s+)?(?:option|choice)[^\n]*|press\s+(?:enter|return)\s+to\s+(?:confirm|select)[^\n]*)")
# Menu cursors as terminals draw them and as OCR tends to read them.
CURSOR = r"[>›»→❯▶►➤●]"
OPTION = re.compile(rf"^(?:{CURSOR}\s*)?([1-9il])[.)]\s*\S", re.MULTILINE)
SELECTED = re.compile(rf"^{CURSOR}\s*(?:[1-9il][.)]\s*)?(\S[^\n]*)$", re.MULTILINE)


# OpenCode draws "Allow once / Allow always / Reject" as buttons and marks the
# selected one only with a filled background, which OCR often cannot read.
OPENCODE_PROMPT = re.compile(r"permission\s+required")
OPENCODE_BUTTONS = re.compile(r"^[^\n]*\b(?:allow|reject)\b[^\n]*\bconfirm\b", re.MULTILINE)
OPENCODE_OPTIONS = ("allow once", "allow always", "reject")


def opencode_selected(image, ocr):
    """The label of the one highlighted OpenCode option, or None when unclear."""
    from .highlight import find_highlights
    labels = []
    for box in find_highlights(image):
        label = " ".join(normalize(ocr.read(image.crop(box))).split())
        if label in OPENCODE_OPTIONS:
            labels.append(label)
    return labels[0] if len(labels) == 1 else None


def latest_menu(text):
    """The latest question followed by two or more numbered options, the text
    after it, and the question with the few lines above it (usually the command)."""
    for found in reversed(list(QUESTION.finditer(text))):
        tail = text[found.end():]
        if len(options(tail)) >= 2:
            above = text[:found.start()].splitlines()[-4:]
            return found.group().strip(), tail, "\n".join(above + [found.group().strip()])
    return None, "", ""


def options(tail):
    return {"1" if number in "il" else number for number in OPTION.findall(tail)}


def selected_yes(tail: str) -> bool:
    """True for a menu of two or more numbered options whose single cursor line says Yes."""
    selected = SELECTED.findall(tail)
    return len(options(tail)) >= 2 and len(selected) == 1 and re.match(r"yes\b", selected[0]) is not None


class PromptGate:
    """Require stable recognition; latch until the prompt is absent long enough.

    Timings use a caller supplied monotonic clock, so wall-clock changes cannot
    affect the gate. mark_fired happens only after delivery (or a dry-run event).
    """
    def __init__(self, settle=0.7, clear=1.0, cooldown=2.0):
        self.settle = settle
        self.clear = clear
        self.cooldown = cooldown
        self.candidate = None
        self.since = None
        self.absent_since = None
        self.latched = False
        self.last_fired = float("-inf")
        self.fired_key = None
        self.observations = 0

    def observe(self, match, now: float) -> bool:
        if match is None:
            self.candidate = None
            self.since = None
            self.observations = 0
            if self.absent_since is None:
                self.absent_since = now
            if now - self.absent_since >= self.clear:
                self.latched = False
            return False
        self.absent_since = None
        key = match.key or match.rule
        if self.latched and key != self.fired_key:
            # A different prompt replaced the handled one.
            self.latched = False
        if key != self.candidate:
            self.candidate = key
            self.since = now
            self.observations = 1
        else:
            self.observations += 1
        return (not self.latched and self.observations >= 2
                and now - self.since >= self.settle
                and now - self.last_fired >= self.cooldown)

    def mark_fired(self, now: float):
        self.latched = True
        self.fired_key = self.candidate
        self.last_fired = now
