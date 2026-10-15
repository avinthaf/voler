"""Run code inside a macOS sandbox that can only write to one folder."""

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def profile_text(root: Path) -> str:
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            f'(allow file-write* (subpath "{root}"))',
            '(allow file-write* (literal "/dev/null"))',
            "(deny network*)",
        ]
    )


@contextmanager
def sandbox_profile(root):
    """Write a profile file that allows writes only inside root. Yield its path."""
    root = Path(root).resolve()
    with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as handle:
        handle.write(profile_text(root))
    try:
        yield handle.name
    finally:
        os.unlink(handle.name)


def run_sandboxed(root, argv: list, timeout: int = 20) -> subprocess.CompletedProcess:
    """Run a command with cwd=root. A timeout returns exit code 124."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with sandbox_profile(root) as profile:
        try:
            return subprocess.run(
                ["sandbox-exec", "-f", profile, *argv],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, 124, "", "timed out")


def run_python(root, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    """Run this project's Python inside the sandbox."""
    return run_sandboxed(root, [sys.executable, *args], timeout)
