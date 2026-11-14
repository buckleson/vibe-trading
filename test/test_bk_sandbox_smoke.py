"""T08: the live Sandbox smoke test under pytest.

Runs every check of scripts/bk_smoke.py once against the running app
(BUCKLESON_SMOKE_URL, default http://127.0.0.1:5000) and reports each as its
own test. Without a server (CI) the whole module is skipped.

    BUCKLESON_SMOKE_URL=http://127.0.0.1:5000 uv run pytest test/test_bk_sandbox_smoke.py -o addopts="" -q
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

import httpx
import pytest

URL = os.getenv("BUCKLESON_SMOKE_URL", "http://127.0.0.1:5000").rstrip("/")

try:
    httpx.get(f"{URL}/auth/session-status", timeout=3).raise_for_status()
except Exception:  # noqa: BLE001 - any failure means no server to test against
    pytest.skip(f"no Buckleson server at {URL}", allow_module_level=True)

_spec = importlib.util.spec_from_file_location(
    "bk_smoke", Path(__file__).resolve().parent.parent / "scripts" / "bk_smoke.py"
)
bk_smoke = importlib.util.module_from_spec(_spec)
sys.modules["bk_smoke"] = bk_smoke  # dataclasses look the module up by name
_spec.loader.exec_module(bk_smoke)


@pytest.fixture(scope="module")
def results():
    return bk_smoke.run(URL, out=io.StringIO())


@pytest.mark.parametrize("name", [name for name, _ in bk_smoke.CHECKS])
def test_smoke_check(results, name):
    assert name in results, "an earlier check stopped the run (server or API key)"
    outcome, detail = results[name]
    if outcome == "SKIP":
        pytest.skip(detail)
    assert outcome == "PASS", detail
