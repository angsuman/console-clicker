from clicker.journal import Journal


def test_journal_appends_readable_entries(tmp_path):
    path = tmp_path / "logs" / "approvals.log"
    journal = Journal(path)
    journal.record("Console 1 · bash", "Command approval", "Run this command?\n\n> 1. Yes\n2. No")
    journal.record("Console 2 · zsh", "Choice menu", "Apply?\n> 1. Yes\n2. No", dry_run=True)
    text = path.read_text(encoding="utf-8")
    assert "APPROVED  [Console 1 · bash]  Command approval\n    Run this command?\n    > 1. Yes\n    2. No\n\n" in text
    assert "WOULD APPROVE (test mode)  [Console 2 · zsh]  Choice menu" in text
    assert text.index("Console 1") < text.index("Console 2")
