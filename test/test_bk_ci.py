"""T11: the Windows workflow runs every Buckleson test, and the docs match the run.

Reads .github/workflows/windows.yml as text (no YAML dependency). The docs
checks describe the finished run, so they fail until T11 updates CLAUDE.md,
docs/CHANGELOG.md and docs/buckleson/TODO.md.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "windows.yml"

NEW_VITEST_FILES = [
    "src/components/portfolio/SymbolSearchInput.test.tsx",
    "src/config/platformsRemoved.test.ts",
    "src/components/claude/ConnectClaude.test.tsx",
    "src/stores/claudeLogin.test.ts",
    "src/pages/OrderSurfaces.test.tsx",
]


def _step_command(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"- name: {re.escape(name)}\n(?:\s+[a-z-]+:.*\n)*?\s+run: (.+)\n", text)
    assert match, f"step '{name}' with a one-line run: missing from windows.yml"
    return match.group(1).strip()


def _backend_files() -> list[str]:
    return [a for a in shlex.split(_step_command("Backend tests")) if a.startswith("test/")]


def _vitest_paths() -> list[str]:
    return [a for a in shlex.split(_step_command("Frontend tests")) if a.startswith("src/")]


def test_every_bk_pytest_file_runs_on_windows():
    listed = set(_backend_files())
    expected = {f"test/{p.name}" for p in (REPO / "test").glob("test_bk_*.py")}
    expected |= {"test/test_paper_broker.py", "test/test_buckleson_bridge.py"}
    assert expected - listed == set()


def test_every_backend_file_named_exists():
    missing = [f for f in _backend_files() if not (REPO / f).is_file()]
    assert missing == []


def test_backend_step_disables_repo_addopts():
    assert '-o addopts=""' in _step_command("Backend tests")


@pytest.mark.parametrize("path", NEW_VITEST_FILES)
def test_new_vitest_file_runs_on_windows(path):
    assert (REPO / "frontend" / path).is_file(), f"{path} is missing"
    assert any(path == p or path.startswith(p.rstrip("/") + "/") for p in _vitest_paths()), path


def test_every_vitest_path_named_exists():
    missing = [p for p in _vitest_paths() if not (REPO / "frontend" / p).exists()]
    assert missing == []


def test_smoke_script_exists_and_is_wired():
    assert (REPO / "scripts" / "bk_smoke.py").is_file()
    assert "test/test_bk_sandbox_smoke.py" in _backend_files()


# -- docs, at the end of the run ------------------------------------------------


def test_changelog_has_buckleson_stanza():
    text = (REPO / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^#+ .*Buckleson.*$", text, re.M)
    assert match, "no Buckleson heading in docs/CHANGELOG.md"
    stanza = text[match.start(): match.start() + 4000]
    for needle in ("Zerodha", "Sandbox", "TradingView", "Claude"):
        assert needle in stanza, f"stanza does not mention {needle}"


def test_claude_md_overview_and_security_updated():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| Unified Broker API"))
    assert not re.search(r"TradingView|Amibroker|ChartInk", row, re.I), row
    assert "TradingView, GoCharting, Chartink" not in text
    assert "docs/buckleson/" in text


def test_todo_board_rows_are_done():
    text = (REPO / "docs" / "buckleson" / "TODO.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if re.match(r"^\| T\d\d \|", line)]
    assert rows, "no board rows"
    not_done = [r.split("|")[1].strip() for r in rows if r.rstrip().rstrip("|").split("|")[-1].strip() != "done"]
    assert not_done == []
