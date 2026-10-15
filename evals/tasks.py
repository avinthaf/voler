"""Eval tasks.

Each task has a starting project, a check, and a known solution.
The solution is only used by the tests. They prove that each check rejects the
untouched start and accepts a correct answer.
"""

import ast
import re

from evals.helpers import (  # noqa: F401 - the backend tasks import these helpers too
    Task,
    defines,
    functions,
    imports_from,
    parse,
    read,
    returns_binop,
    unchanged,
    unittest_passes,
    write,
)
from evals.sandbox import run_python
from pathlib import Path


# ---------- easy tasks ----------

PROJECT = {
    "greet.py": 'print("hello from greet")\n',
    "a.py": "x = 1\n",
    "b.py": "y = 2\n",
    "notes.txt": "not python\n",
    "data.txt": "one\ntwo\nthree\nfour\n",
}


def check_r1(root, reply):
    return "hello from greet" in reply.lower()


def check_r2(root, reply):
    low = reply.lower()
    return all(f in low for f in ("a.py", "b.py", "greet.py")) and "notes.txt" not in low and "data.txt" not in low


def check_r3(root, reply):
    return bool(re.search(r"\b4\b|\bfour\b", reply.lower()))


def check_w1(root, reply):
    tree = parse(read(root, "hello.py"))
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "hello" in arg.value.lower():
                    return True
    return False


def check_w2(root, reply):
    tree = parse(read(root, "buggy.py"))
    if tree is None:
        return False
    func = functions(tree).get("add")
    if func is None or [a.arg for a in func.args.args] != ["a", "b"]:
        return False
    return returns_binop(func, ast.Add, "a", "b") or returns_binop(func, ast.Add, "b", "a")


def check_w3(root, reply):
    tree = parse(read(root, "greet.py"))
    if tree is None:
        return False
    funcs = functions(tree)
    func = funcs.get("welcome")
    if func is None or "greet" in funcs or [a.arg for a in func.args.args] != ["name"]:
        return False
    return returns_binop(func, ast.Add, "hi ", "name")


CALC = (
    "def total(prices):\n    return sum(prices) * 1.07  # tax\n\n\n"
    "def average(prices):\n    return sum(prices) / len(prices)\n"
)


def check_w4(root, reply):
    tree = parse(read(root, "calc.py"))
    if tree is None:
        return False
    funcs = functions(tree)
    if "total" not in funcs or "average" not in funcs:
        return False
    if ast.dump(funcs["average"]) != ast.dump(functions(ast.parse(CALC))["average"]):
        return False
    for node in ast.walk(funcs["total"]):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Mult):
            right = node.value.right
            if isinstance(right, ast.Constant) and right.value == 1.1:
                return True
    return False


def solve_w1(root):
    write(root, "hello.py", 'print("hello")\n')
    return "Created hello.py."


def solve_w2(root):
    write(root, "buggy.py", "def add(a, b):\n    return a + b\n")
    return "Fixed add."


def solve_w3(root):
    write(root, "greet.py", 'def welcome(name):\n    return "hi " + name\n')
    return "Renamed greet to welcome."


def solve_w4(root):
    write(root, "calc.py", CALC.replace("1.07", "1.10"))
    return "Changed the tax rate."


EASY = [
    Task("r1_read_print", "easy", "What does greet.py print? Read the file to find out.", PROJECT,
         check_r1, lambda root: "It prints hello from greet."),
    Task("r2_list_py", "easy", "List the Python files in this folder.", PROJECT,
         check_r2, lambda root: "a.py, b.py, greet.py"),
    Task("r3_count_lines", "easy", "How many lines are in data.txt?", PROJECT,
         check_r3, lambda root: "data.txt has 4 lines."),
    Task("w1_create", "easy", "Create a file hello.py that prints hello.", {}, check_w1, solve_w1),
    Task("w2_fix_bug", "easy",
         "buggy.py has a function add(a, b) that is wrong. Fix it so it adds the two numbers.",
         {"buggy.py": "def add(a, b):\n    return a - b\n"}, check_w2, solve_w2),
    Task("w3_rename", "easy", "Rename the function greet to welcome in greet.py.",
         {"greet.py": 'def greet(name):\n    return "hi " + name\n'}, check_w3, solve_w3),
    Task("w4_edit_unseen", "easy",
         "In calc.py, change the tax rate in total() from 1.07 to 1.10. Keep everything else the same.",
         {"calc.py": CALC}, check_w4, solve_w4),
]

# ---------- hard tasks ----------

H1_FILES = {
    "utils.py": 'def slugify(text):\n    return text.strip().lower().replace(" ", "-")\n',
    "app.py": 'from utils import slugify\n\n\ndef make_url(title):\n    return "/posts/" + slugify(title)\n',
    "test_app.py": (
        "import unittest\n\nfrom app import make_url\nfrom utils import slugify\n\n\n"
        "class AppTests(unittest.TestCase):\n"
        "    def test_make_url(self):\n"
        '        self.assertEqual(make_url("Hello World"), "/posts/hello-world")\n\n'
        "    def test_slug(self):\n"
        '        self.assertEqual(slugify("  A B "), "a-b")\n'
    ),
}


def check_h1(root, reply):
    if any("slugify" in path.read_text() for path in Path(root).rglob("*.py")):
        return False
    tree = parse(read(root, "utils.py"))
    return tree is not None and "make_slug" in functions(tree) and unittest_passes(root, 2)


def solve_h1(root):
    for name, text in H1_FILES.items():
        write(root, name, text.replace("slugify", "make_slug"))
    return "Renamed it everywhere."


H2_TESTS = (
    "import unittest\n\nfrom shop import apply_discount, total\n\n\n"
    "class ShopTests(unittest.TestCase):\n"
    "    def test_total_uses_quantity(self):\n"
    "        self.assertEqual(total([(2, 3), (5, 1)]), 11)\n\n"
    "    def test_total_empty(self):\n"
    "        self.assertEqual(total([]), 0)\n\n"
    "    def test_discount(self):\n"
    "        self.assertEqual(apply_discount(200, 10), 180)\n\n"
    "    def test_no_discount(self):\n"
    "        self.assertEqual(apply_discount(50, 0), 50)\n"
)
H2_FILES = {
    "shop.py": (
        "def total(items):\n"
        '    """Return the total price. items is a list of (price, quantity) pairs."""\n'
        "    return sum(price for price, quantity in items)\n\n\n"
        "def apply_discount(amount, percent):\n"
        "    return amount - amount * percent\n"
    ),
    "test_shop.py": H2_TESTS,
}


def check_h2(root, reply):
    return read(root, "test_shop.py") == H2_TESTS and unittest_passes(root, 4)


def solve_h2(root):
    text = H2_FILES["shop.py"]
    text = text.replace("sum(price for", "sum(price * quantity for").replace("amount * percent", "amount * percent / 100")
    write(root, "shop.py", text)
    return "Fixed both bugs."


H3_FILES = {
    "stats.py": (
        "def mean(numbers):\n    return sum(numbers) / len(numbers)\n\n\n"
        "def maximum(numbers):\n    return max(numbers)\n"
    ),
}
H3_CHECK = (
    "from stats import mean, maximum, median\n"
    "assert median([3, 1, 2]) == 2\n"
    "assert median([4, 1, 3, 2]) == 2.5\n"
    "assert median([7]) == 7\n"
    "assert median([5, 1]) == 3\n"
    "assert mean([1, 2, 3]) == 2\n"
    "assert maximum([1, 9, 3]) == 9\n"
)


def check_h3(root, reply):
    return run_python(root, "-c", H3_CHECK).returncode == 0


def solve_h3(root):
    write(root, "stats.py", H3_FILES["stats.py"] + (
        "\n\ndef median(numbers):\n"
        "    ordered = sorted(numbers)\n"
        "    middle = len(ordered) // 2\n"
        "    if len(ordered) % 2:\n"
        "        return ordered[middle]\n"
        "    return (ordered[middle - 1] + ordered[middle]) / 2\n"
    ))
    return "Added median."


H4_FILES = {
    "greetings.py": 'def greet(name):\n    return "hi " + name\n',
    "main.py": "import sys\n\nfrom greetings import greet\n\nif __name__ == \"__main__\":\n    print(greet(sys.argv[1]))\n",
}
H4_API = (
    "from greetings import greet\n"
    "assert greet('a') == 'hi a'\n"
    "assert greet('a', shout=True) == 'HI A'\n"
    "assert greet('a', False) == 'hi a'\n"
)


def check_h4(root, reply):
    quiet = run_python(root, "main.py", "bob")
    loud = run_python(root, "main.py", "bob", "loud")
    api = run_python(root, "-c", H4_API)
    return quiet.stdout == "hi bob\n" and loud.stdout == "HI BOB\n" and api.returncode == 0


def solve_h4(root):
    write(root, "greetings.py", (
        "def greet(name, shout=False):\n"
        '    text = "hi " + name\n'
        "    return text.upper() if shout else text\n"
    ))
    write(root, "main.py", (
        "import sys\n\nfrom greetings import greet\n\n"
        'if __name__ == "__main__":\n'
        '    shout = len(sys.argv) > 2 and sys.argv[2] == "loud"\n'
        "    print(greet(sys.argv[1], shout=shout))\n"
    ))
    return "Added the shout option."


H5_FILES = {
    "app.py": (
        "def parse_line(line):\n"
        '    key, value = line.split("=", 1)\n'
        "    return key.strip(), value.strip()\n\n\n"
        "def load(text):\n"
        "    return dict(parse_line(line) for line in text.splitlines() if line.strip())\n"
    ),
    "test_app.py": (
        "import unittest\n\nfrom app import load\n\n\n"
        "class LoadTests(unittest.TestCase):\n"
        "    def test_load(self):\n"
        '        self.assertEqual(load("a = 1\\nb=2\\n"), {"a": "1", "b": "2"})\n\n'
        "    def test_blank_lines(self):\n"
        '        self.assertEqual(load("\\n\\nx=y\\n"), {"x": "y"})\n'
    ),
}


def check_h5(root, reply):
    return (
        defines(root, "parser.py", "parse_line")
        and not defines(root, "app.py", "parse_line")
        and imports_from(root, "app.py", "parser", "parse_line")
        and unittest_passes(root, 2)
    )


def solve_h5(root):
    write(root, "parser.py", (
        "def parse_line(line):\n"
        '    key, value = line.split("=", 1)\n'
        "    return key.strip(), value.strip()\n"
    ))
    write(root, "app.py", (
        "from parser import parse_line\n\n\n"
        "def load(text):\n"
        "    return dict(parse_line(line) for line in text.splitlines() if line.strip())\n"
    ))
    return "Moved parse_line to parser.py."


H6_FILES = {
    "config.py": (
        "import json\n\n\n"
        "def load_config(path):\n    with open(path) as handle:\n        return json.load(handle)\n\n\n"
        'def load_defaults():\n    return {"port": 8000}\n'
    ),
    "server.py": (
        "from config import load_config\n\n\n"
        "def start_server(path):\n    settings = load_config(path)\n    return settings[\"port\"]\n"
    ),
    "worker.py": (
        "from config import load_defaults\n\n\n"
        "def run_worker():\n"
        "    # Does not use load_config. It only needs the defaults.\n"
        '    return load_defaults()["port"]\n'
    ),
    "cache.py": "def reload_config_cache():\n    return {}\n",
}


def check_h6(root, reply):
    low = reply.lower()
    return (
        "start_server" in low
        and "server.py" in low
        and "run_worker" not in low
        and "reload_config_cache" not in low
        and unchanged(root, H6_FILES)
    )


H7_FILES = {
    "reports.py": 'def build():\n    return "ok"\n',
    "README.md": "A small reporting tool.\n",
}
NOT_FOUND = re.compile(
    r"not found|doesn't exist|does not exist|no such file|couldn't find|could not find"
    r"|cannot find|can't find|no file named|no file called|reports\.py",
    re.IGNORECASE,
)


def check_h7(root, reply):
    return (
        not Path(root, "report.py").exists()
        and read(root, "reports.py") == H7_FILES["reports.py"]
        and bool(NOT_FOUND.search(reply))
    )


HARD = [
    Task("h1_rename_everywhere", "hard",
         "Rename the function slugify to make_slug everywhere in this project, including its callers and tests.",
         H1_FILES, check_h1, solve_h1),
    Task("h2_fix_failing_tests", "hard",
         "The tests in test_shop.py fail. Run them, find the bugs in shop.py, and fix them. Do not change the tests.",
         H2_FILES, check_h2, solve_h2),
    Task("h3_add_function", "hard",
         "Add a function median(numbers) to stats.py that returns the median of a list of numbers. "
         "Keep the existing functions.",
         H3_FILES, check_h3, solve_h3),
    Task("h4_two_file_feature", "hard",
         "Add an optional shout parameter (default False) to greet() in greetings.py. "
         "When it is True, return the greeting in upper case. "
         "Then change main.py so that if a second command-line argument is 'loud', it calls greet with shout=True.",
         H4_FILES, check_h4, solve_h4),
    Task("h5_move_function", "hard",
         "Move parse_line out of app.py into a new file parser.py. "
         "app.py should import it from there. The tests must still pass.",
         H5_FILES, check_h5, solve_h5),
    Task("h6_find_caller", "hard",
         "Which function calls load_config? Answer with the function name and the file it is in. "
         "Do not change any files.",
         H6_FILES, check_h6, lambda root: "start_server in server.py calls load_config."),
    Task("h7_missing_file", "hard", "Fix the bug in report.py.", H7_FILES, check_h7,
         lambda root: "There is no report.py. I found reports.py but did not change it."),
]

from evals.backend_tasks import BACKEND, VARIANTS  # noqa: E402

TASKS = EASY + HARD + BACKEND + VARIANTS
TASKS_BY_ID = {task.id: task for task in TASKS}
