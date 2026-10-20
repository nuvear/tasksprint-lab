"""scripts/mcp_smoke.py against a spawned lab: real client, PASS lines, no secrets printed."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from services.lab.config import parse_env_file

pytestmark = pytest.mark.protocol
REPO = Path(__file__).resolve().parents[2]


def test_smoke_script_reports_role_matrix_without_printing_tokens(stack):
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "mcp_smoke.py"), "--lab-url", stack.url,
                          "--tokens-file", str(stack.tokens_file), "--call-state"],
                         capture_output=True, text=True, timeout=120, cwd=REPO)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "RESULT PASS" in out.stdout and "FAIL" not in out.stdout
    assert "PASS developer protocol 2025-11-25: 6 tools" in out.stdout
    for value in parse_env_file(stack.tokens_file).values():
        assert value not in out.stdout and value not in out.stderr
