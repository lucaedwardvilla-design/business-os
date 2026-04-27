"""Generation backend (LOCAL ONLY).

Subprocess to the local `claude` CLI. Uses the user's Claude Code subscription.

Cloud execution path: see ROUTINE.md — the Claude Code Routine generates content
natively (Claude IS the generator in the routine context). gen.py is not used
in cloud mode.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("seo-engine.gen")


def have_claude_cli() -> bool:
    return shutil.which("claude") is not None


def generate(prompt: str) -> str:
    """Generate a post via the local claude CLI. Returns raw model output."""
    if not have_claude_cli():
        raise EnvironmentError(
            "`claude` CLI not on PATH. This module is for local subscription use; "
            "for cloud execution, use the Claude Code Routine (see ROUTINE.md)."
        )
    try:
        result = subprocess.run(
            ["claude", "--print", "--output-format", "text",
             "--model", "claude-sonnet-4-6"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log.error("claude CLI failed: rc=%s stderr=%s", e.returncode, e.stderr[:500])
        raise
