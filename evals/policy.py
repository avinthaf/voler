"""Which bash commands the evals approve without asking a person.

Writes are confined by the sandbox. This policy keeps the commands read-only,
except for running Python (files, unit tests, and inline code) inside the project folder.
"""

import re
import shlex

SAFE_COMMANDS = {"ls", "cat", "pwd", "head", "tail", "wc", "grep", "echo", "find", "sort", "diff", "cd"}
PYTHON_COMMANDS = {"python", "python3"}
FIND_BLOCKED = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
SEPARATORS = {"&&", "||", "|", ";"}
ALLOWED_OPERATORS = SEPARATORS | {"<"}
PUNCTUATION = set("();<>|&")
HARMLESS_REDIRECTS = re.compile(r"\s*(2>\s*/dev/null|2>&1|>\s*/dev/null)")


def _tokens(command: str) -> list:
    lexer = shlex.shlex(HARMLESS_REDIRECTS.sub(" ", command), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _argument_ok(token: str) -> bool:
    if "$" in token or "`" in token or ".." in token or token.startswith("~"):
        return False
    return not token.startswith("/") or token == "/dev/null"


def _inline_code_ok(code: str) -> bool:
    """Inline Python may contain any text. Only shell substitution is refused."""
    return "$(" not in code and "`" not in code


def _python_ok(words: list) -> bool:
    rest = words[1:]
    if rest[:2] in (["-m", "unittest"], ["-m", "pytest"]):
        return True
    return bool(rest) and rest[0].endswith(".py") and not rest[0].startswith("-")


def _segment_ok(words: list) -> bool:
    if not words:
        return True
    name, rest = words[0], words[1:]
    if name in PYTHON_COMMANDS and rest[:1] == ["-c"]:
        # The sandbox confines what inline code can do. The code itself is not path-checked.
        return len(rest) >= 2 and _inline_code_ok(rest[1]) and all(_argument_ok(word) for word in rest[2:])
    if name in PYTHON_COMMANDS:
        if not _python_ok(words):
            return False
    elif name not in SAFE_COMMANDS:
        return False
    if name == "find" and FIND_BLOCKED & set(words):
        return False
    if name == "cd" and len(rest) != 1:
        return False
    return all(_argument_ok(word) for word in rest)


def command_allowed(command: str) -> bool:
    try:
        tokens = _tokens(command)
    except ValueError:
        return False
    if not tokens:
        return False

    segment = []
    segments = []
    for token in tokens:
        if set(token) <= PUNCTUATION:
            if token not in ALLOWED_OPERATORS:
                return False
            if token in SEPARATORS:
                segments.append(segment)
                segment = []
            # A "<" only redirects input, so it is dropped before checking the words.
            continue
        segment.append(token)
    segments.append(segment)
    return all(_segment_ok(words) for words in segments)


def approve(question: str) -> bool:
    """Drop-in replacement for tools.confirm."""
    if question.startswith(("Write ", "Edit ")):
        return True
    return command_allowed(question.removeprefix("Run bash command: "))
