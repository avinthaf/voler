import subprocess
from pathlib import Path

# Folder the file tools may touch. Change it with set_root().
ROOT = Path.cwd().resolve()

BASH_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000
PREVIEW_CHARS = 300

# Path to a macOS sandbox profile. When set, bash commands run inside it.
SANDBOX_PROFILE: str | None = None

# Added to every "denied" message so the model knows not to retry.
DENIED_HINT = " Do not retry it. Use relative paths inside the project folder, or say what you could not do."

# When True, changing an existing file needs a read_file of it first.
REQUIRE_READ_BEFORE_CHANGE = True

# Files the model has read or written in this session.
_known_files: set[Path] = set()


def set_root(path: str) -> None:
    """Set the project folder. Evals call this to use a throwaway folder."""
    global ROOT
    ROOT = Path(path).resolve()
    reset_session()


def reset_session() -> None:
    """Forget which files the model has read."""
    _known_files.clear()


def ask_user(question: str) -> bool:
    """Ask the user for a yes or no. Anything but 'y' means no."""
    return input(f"{question} [y/N] ").strip().lower() == "y"


# Tools call confirm() through this name. Tests can swap it out.
confirm = ask_user


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    cut = len(text) - MAX_OUTPUT_CHARS
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {cut} characters]"


def _preview(text: str) -> str:
    if len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS] + "..."


def _resolve(path: str) -> Path:
    """Turn a path into an absolute one. Raise ValueError if it leaves ROOT."""
    full = (ROOT / path).resolve()
    if not full.is_relative_to(ROOT):
        raise ValueError(f"path is outside the project folder: {path}")
    return full


def _unread_error(full: Path, path: str) -> str | None:
    """Return an error if the model is changing an existing file it has not read."""
    if REQUIRE_READ_BEFORE_CHANGE and full.exists() and full not in _known_files:
        return f"Error: {path} already exists and you have not read it. Read it with read_file first."
    return None


def bash(command: str) -> str:
    """Run a shell command in the project folder and return its output.

    Args:
        command: The shell command to run.
    """
    if not confirm(f"Run bash command: {command}"):
        return "Error: the user denied this command." + DENIED_HINT
    if SANDBOX_PROFILE:
        argv = ["sandbox-exec", "-f", SANDBOX_PROFILE, "/bin/sh", "-c", command]
    else:
        argv = command
    try:
        result = subprocess.run(
            argv,
            shell=not SANDBOX_PROFILE,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {BASH_TIMEOUT_SECONDS} seconds"
    output = result.stdout + result.stderr
    return _truncate(f"exit code: {result.returncode}\n{output}")


def read_file(path: str) -> str:
    """Read a text file and return its contents.

    Args:
        path: Path to the file, relative to the project folder.
    """
    try:
        full = _resolve(path)
        text = full.read_text()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except (ValueError, OSError, UnicodeDecodeError) as e:
        return f"Error: {e}"
    _known_files.add(full)
    return _truncate(text)


def write_file(path: str, content: str) -> str:
    """Create a file or overwrite an existing one.

    Args:
        path: Path to the file, relative to the project folder.
        content: The full text to write to the file.
    """
    try:
        full = _resolve(path)
    except ValueError as e:
        return f"Error: {e}"
    unread = _unread_error(full, path)
    if unread:
        return unread
    if not confirm(f"Write {len(content)} characters to {path}:\n{_preview(content)}"):
        return "Error: the user denied this write." + DENIED_HINT
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    except OSError as e:
        return f"Error: {e}"
    _known_files.add(full)
    return f"Wrote {len(content)} characters to {path}"


def edit_file(path: str, old: str, new: str) -> str:
    """Replace one exact piece of text in a file with new text.

    Args:
        path: Path to the file, relative to the project folder.
        old: The exact text to replace. It must appear in the file once.
        new: The text to put in its place.
    """
    try:
        full = _resolve(path)
    except ValueError as e:
        return f"Error: {e}"
    if not full.is_file():
        return f"Error: file not found: {path}"
    unread = _unread_error(full, path)
    if unread:
        return unread
    try:
        text = full.read_text()
    except (OSError, UnicodeDecodeError) as e:
        return f"Error: {e}"
    if not old:
        return "Error: old must not be empty"
    count = text.count(old)
    if count == 0:
        return f"Error: the text to replace was not found in {path}. Copy it exactly from the file."
    if count > 1:
        return f"Error: the text appears {count} times in {path}. Include more surrounding text so it matches once."
    if not confirm(f"Edit {path}: replace\n{_preview(old)}\nwith\n{_preview(new)}"):
        return "Error: the user denied this edit." + DENIED_HINT
    try:
        full.write_text(text.replace(old, new, 1))
    except OSError as e:
        return f"Error: {e}"
    return f"Edited {path}: replaced 1 occurrence"


TOOLS = [bash, read_file, write_file, edit_file]
TOOLS_BY_NAME = {tool.__name__: tool for tool in TOOLS}
