import re
import pytest
from clicker.core import Match, PromptGate, PromptMatcher


PROMPT = "Requesting permission for:\n sed -n '285,305p' file.java\nRun this command?\n> 1. Yes, run command\n 2. Yes, always allow\n 4. No, cancel"


def test_reference_prompt():
    assert PromptMatcher().match(PROMPT).rule == "Command approval"


@pytest.mark.parametrize("text", ["", "Working…", "Run this command?", "1. Yes, run command", "Run this command\n1. Yes", "1. Apples\n2. Oranges", "Tests passed: 1. Yes\n2. Good"])
def test_incomplete_or_ordinary_output_is_ignored(text):
    assert PromptMatcher().match(text) is None


@pytest.mark.parametrize("text", ["Apply this change?\n● 1. Yes, allow once\n2. Yes, allow always\n3. No",
                                  "Do you want to make this edit to core.py?\n❯ 1. Yes\n2. Yes, allow all edits\n3. No, and tell Claude what to do differently?",
                                  "Press Enter to confirm\n> 1. Yes\n2. No"])
def test_numbered_choice_menu(text):
    assert PromptMatcher(approvals=False).match(text).rule == "Choice menu"


@pytest.mark.parametrize("text", [
    # A numbered list in an AI reply has no cursor.
    "Which approach is better?\n1. Yes, use Redis\n2. Use Postgres",
    "Which environment?\n1) Test\n2) Production",
    # The cursor is on something other than Yes.
    "Do you want to proceed?\n1. Yes\n> 2. No",
    "Choose an option:\n> 1. Retry\n2. Exit",
    # Two cursors are bullets, not a menu selection.
    "Do you want to proceed?\n> 1. Yes\n> 2. No",
    # An older answered menu above a newer question is stale.
    "Run this command?\n> 1. Yes\n2. No\nDone.\nWhich database?\n1. A\n2. B",
])
def test_only_a_yes_cursor_on_the_latest_menu_fires(text):
    assert PromptMatcher().match(text) is None


def test_box_borders_are_ignored():
    text = "| Bash command |\n| rm -rf build |\n| Do you want to proceed? |\n│ ❯ 1. Yes │\n| 2. No |"
    assert PromptMatcher().match(text).rule == "Command approval"


def test_normalization_and_ocr_variations():
    assert PromptMatcher().match("RUN   THIS COMMAND ?\n› l. Yes, run command\n2. No").rule == "Command approval"


def test_custom_rule_and_disabled_builtins():
    matcher = PromptMatcher(False, False, r"press\s+enter\s+to\s+continue")
    assert matcher.match("Press ENTER to continue").rule == "Custom rule"
    assert matcher.match(PROMPT) is None


@pytest.mark.parametrize("pattern", [".*", "^", r"\s*"])
def test_empty_matching_custom_rules_rejected(pattern):
    with pytest.raises(ValueError):
        PromptMatcher(custom=pattern)


def test_invalid_custom_rule():
    with pytest.raises(re.error):
        PromptMatcher(custom="[")
    with pytest.raises(ValueError):
        PromptMatcher(False, False, opencode=False)


def test_gate_requires_two_stable_observations_and_suppresses_duplicates():
    match = Match("Approval", "question")
    gate = PromptGate()
    assert not gate.observe(match, 10)
    assert not gate.observe(match, 10.4)
    assert gate.observe(match, 10.8)
    gate.mark_fired(10.8)
    for time in [11, 20, 100]:
        assert not gate.observe(match, time)


def test_gate_rearms_after_absence_and_respects_cooldown():
    match = Match("Approval", "question")
    gate = PromptGate(settle=0.3, clear=0.5, cooldown=2)
    gate.observe(match, 0)
    assert gate.observe(match, 0.4)
    gate.mark_fired(0.4)
    gate.observe(None, 0.5)
    gate.observe(None, 1.1)
    gate.observe(match, 1.2)
    assert not gate.observe(match, 1.8)
    assert gate.observe(match, 2.5)


def test_one_ocr_dropout_does_not_rearm():
    match = Match("Approval", "question")
    gate = PromptGate()
    gate.observe(match, 0)
    gate.mark_fired(1)
    gate.observe(None, 2)
    assert not gate.observe(match, 2.5)
    assert not gate.observe(match, 4)


def test_rule_change_must_settle_again():
    gate = PromptGate()
    gate.observe(Match("A", "a"), 0)
    assert not gate.observe(Match("B", "b"), 2)
    assert gate.observe(Match("B", "b"), 3)


def test_gate_does_not_latch_before_delivery():
    match = Match("Approval", "question")
    gate = PromptGate()
    gate.observe(match, 0)
    assert gate.observe(match, 1)
    assert gate.observe(match, 2)


class LabelOCR:
    """Reads a highlighted crop as a given label; enough to test the rule's logic."""
    def __init__(self, label):
        self.label = label

    def read(self, image):
        return self.label


OPENCODE = "△ Permission required\n# Shell command\n$ rm -rf build\nAllow always Reject ctrl+f fullscreen ⇆ select enter confirm"


def highlighted_screen():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (600, 120), (10, 10, 10))
    ImageDraw.Draw(image).rectangle((20, 60, 130, 80), fill=(250, 178, 60))
    return image


@pytest.mark.parametrize("label, fires", [("Allow once", True), ("Allow always", False), ("Reject", False), ("", False)])
def test_opencode_fires_only_when_allow_once_is_highlighted(label, fires):
    match = PromptMatcher().match(OPENCODE, highlighted_screen(), LabelOCR(label))
    assert (match is not None and match.rule == "OpenCode permission") is fires


def test_opencode_needs_the_image_and_can_be_disabled():
    assert PromptMatcher().match(OPENCODE) is None
    assert PromptMatcher(opencode=False).match(OPENCODE, highlighted_screen(), LabelOCR("Allow once")) is None


def test_a_different_prompt_rearms_without_a_gap_but_the_same_one_does_not():
    gate = PromptGate(settle=0.3, cooldown=2)
    first, second = Match("Approval", "q", "rm -rf build-0"), Match("Approval", "q", "rm -rf build-1")
    gate.observe(first, 0)
    assert gate.observe(first, 0.4)
    gate.mark_fired(0.4)
    assert not gate.observe(first, 5)
    # The next request replaces it immediately; the cooldown still applies.
    assert not gate.observe(second, 1.0)
    assert not gate.observe(second, 1.5)
    assert gate.observe(second, 2.5)


def test_prompt_key_includes_the_command_above_the_question():
    one = PromptMatcher().match("Bash command\nrm -rf build-0\nDo you want to proceed?\n> 1. Yes\n2. No")
    two = PromptMatcher().match("Bash command\nrm -rf build-1\nDo you want to proceed?\n> 1. Yes\n2. No")
    assert one.rule == two.rule and one.key != two.key
