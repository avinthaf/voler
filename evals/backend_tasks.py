"""Backend eval tasks. They build and change small Flask APIs.

The checks run hidden tests against the model's code with Flask's test client.
Nothing starts a real server.
"""

import json
import shutil
import tempfile

from evals.helpers import Task, read, run_python, unittest_passes, write

SERVER_NOTE = " You cannot start a server here. Check your work with Flask's test client."


# ---------- b1: build a todo API from a spec ----------

B1_PROBE = r'''
import json
from app import app

c = app.test_client()
results, state = {}, {}


def probe(name, fn):
    try:
        fn()
        results[name] = True
    except Exception:
        results[name] = False


def create():
    r = c.post("/todos", json={"title": "write tests"})
    assert r.status_code == 201
    todo = r.get_json()
    assert todo["title"] == "write tests" and todo["done"] is False and isinstance(todo["id"], int)
    state["first"] = todo


def second():
    r = c.post("/todos", json={"title": "second"})
    assert r.status_code == 201
    state["second"] = r.get_json()
    assert state["second"]["id"] != state["first"]["id"]


def rejects(payload):
    # The spec names missing, empty, and blank titles. null counts as missing.
    r = c.post("/todos", json=payload)
    assert r.status_code == 400 and isinstance(r.get_json().get("error"), str)


def not_a_crash(**kwargs):
    # The spec is silent about these inputs. Any answer is fine except a server error.
    assert c.post("/todos", **kwargs).status_code < 500


def lists_both():
    r = c.get("/todos")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body, list)
    titles = {item["title"] for item in body}
    assert {"write tests", "second"} <= titles


def get_one():
    r = c.get("/todos/%d" % state["first"]["id"])
    assert r.status_code == 200 and r.get_json()["title"] == "write tests"


def get_missing():
    r = c.get("/todos/9999")
    assert r.status_code == 404 and isinstance(r.get_json().get("error"), str)


def patch_done():
    r = c.patch("/todos/%d" % state["first"]["id"], json={"done": True})
    assert r.status_code == 200
    assert r.get_json()["done"] is True and r.get_json()["title"] == "write tests"


def patch_title():
    r = c.patch("/todos/%d" % state["first"]["id"], json={"title": "renamed"})
    assert r.status_code == 200
    assert r.get_json()["title"] == "renamed" and r.get_json()["done"] is True


def patch_persists():
    todo = c.get("/todos/%d" % state["first"]["id"]).get_json()
    assert todo["done"] is True and todo["title"] == "renamed"


def delete_one():
    r = c.delete("/todos/%d" % state["first"]["id"])
    assert r.status_code == 204 and r.data == b""


def deleted_is_gone():
    assert c.get("/todos/%d" % state["first"]["id"]).status_code == 404


def list_after_delete():
    ids = {item["id"] for item in c.get("/todos").get_json()}
    assert state["first"]["id"] not in ids and state["second"]["id"] in ids


probe("01 create: 201 with id, title, done=false", create)
probe("02 a second todo gets a different id", second)
probe("03 missing title returns 400 with an error", lambda: rejects({}))
probe("04 empty title returns 400 with an error", lambda: rejects({"title": ""}))
probe("05 blank title returns 400 with an error", lambda: rejects({"title": "   "}))
probe("06 null title returns 400 with an error", lambda: rejects({"title": None}))
probe("07 a non-string title does not crash", lambda: not_a_crash(json={"title": 5}))
probe("08 a non-JSON body does not crash", lambda: not_a_crash(data="not json", content_type="text/plain"))
probe("09 GET /todos lists both todos as a bare list", lists_both)
probe("10 GET one todo", get_one)
probe("11 GET unknown id returns 404 with an error", get_missing)
probe("12 PATCH done keeps the title", patch_done)
probe("13 PATCH title keeps done", patch_title)
probe("14 PATCH persists", patch_persists)
probe("15 PATCH unknown id returns 404", lambda: (_ for _ in ()).throw(AssertionError) if c.patch("/todos/9999", json={"done": True}).status_code != 404 else None)
probe("16 DELETE returns 204 with an empty body", delete_one)
probe("17 a deleted todo is gone", deleted_is_gone)
probe("18 the list drops the deleted todo and keeps the other", list_after_delete)
probe("19 DELETE unknown id returns 404", lambda: (_ for _ in ()).throw(AssertionError) if c.delete("/todos/9999").status_code != 404 else None)
print(json.dumps(results))
'''

B1_SOLUTION = r'''from flask import Flask, jsonify, request

app = Flask(__name__)
todos = {}
next_id = 1


def not_found():
    return jsonify({"error": "not found"}), 404


@app.post("/todos")
def create_todo():
    global next_id
    data = request.get_json(silent=True)
    title = data.get("title") if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "title is required"}), 400
    todo = {"id": next_id, "title": title, "done": False}
    todos[next_id] = todo
    next_id += 1
    return jsonify(todo), 201


@app.get("/todos")
def list_todos():
    return jsonify(list(todos.values()))


@app.get("/todos/<int:todo_id>")
def get_todo(todo_id):
    todo = todos.get(todo_id)
    return jsonify(todo) if todo else not_found()


@app.patch("/todos/<int:todo_id>")
def update_todo(todo_id):
    todo = todos.get(todo_id)
    if not todo:
        return not_found()
    data = request.get_json(silent=True) or {}
    if "title" in data:
        todo["title"] = data["title"]
    if "done" in data:
        todo["done"] = bool(data["done"])
    return jsonify(todo)


@app.delete("/todos/<int:todo_id>")
def delete_todo(todo_id):
    if todos.pop(todo_id, None) is None:
        return not_found()
    return "", 204
'''


def detail_b1(root, reply):
    """Run each assertion on its own. A crash or a missing app fails everything."""
    result = run_python(root, "-c", B1_PROBE)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"00 app.py loads and runs": False}


def check_b1(root, reply):
    return all(detail_b1(root, reply).values())


def solve_b1(root):
    write(root, "app.py", B1_SOLUTION)
    return "Created the todo API in app.py."


# ---------- b2: add validation and JSON 404s to an existing app ----------

B2_FILES = {
    "app.py": r'''from flask import Flask, jsonify, request

app = Flask(__name__)
items = []


@app.post("/items")
def create_item():
    data = request.get_json()
    item = {"id": len(items) + 1, "name": data["name"], "price": data["price"]}
    items.append(item)
    return jsonify(item), 201


@app.get("/items")
def list_items():
    return jsonify(items)
''',
    "test_app.py": r'''import unittest

from app import app


class ItemTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_create_item(self):
        response = self.client.post("/items", json={"name": "pen", "price": 1.5})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["name"], "pen")

    def test_list_items(self):
        self.client.post("/items", json={"name": "cup", "price": 3})
        self.assertGreaterEqual(len(self.client.get("/items").get_json()), 1)
''',
}

B2_CHECK = r'''
from app import app
c = app.test_client()
assert c.post("/items", json={"name": "pen", "price": 9.99}).status_code == 201
assert c.post("/items", json={"name": "cup", "price": 5}).status_code == 201

bad_inputs = [
    {"name": "", "price": 1}, {"price": 1}, {"name": "x"},
    {"name": "x", "price": 0}, {"name": "x", "price": -5},
    {"name": "x", "price": "9.99"}, {"name": "x", "price": True},
    {"name": 5, "price": 1}, {"name": None, "price": 1},
]
for bad in bad_inputs:
    r = c.post("/items", json=bad)
    assert r.status_code == 422, (bad, r.status_code)
    assert isinstance(r.get_json().get("error"), str), bad

r = c.get("/no/such/route")
assert r.status_code == 404
assert r.is_json and r.get_json() == {"error": "not found"}, r.data
assert len(c.get("/items").get_json()) == 2
'''

B2_APP_SOLUTION = r'''from flask import Flask, jsonify, request

app = Flask(__name__)
items = []


def invalid(message):
    return jsonify({"error": message}), 422


@app.post("/items")
def create_item():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return invalid("a JSON object is required")
    name, price = data.get("name"), data.get("price")
    if not isinstance(name, str) or not name:
        return invalid("name must be a non-empty string")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        return invalid("price must be a positive number")
    item = {"id": len(items) + 1, "name": name, "price": price}
    items.append(item)
    return jsonify(item), 201


@app.get("/items")
def list_items():
    return jsonify(items)


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "not found"}), 404
'''


def check_b2(root, reply):
    return run_python(root, "-c", B2_CHECK).returncode == 0 and unittest_passes(root, at_least=2)


def solve_b2(root):
    write(root, "app.py", B2_APP_SOLUTION)
    return "Added validation and a JSON 404."


# ---------- b3: fix SQL injection and add a search endpoint ----------

B3_FILES = {
    "db.py": r'''import sqlite3


def connect(path="app.db"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    return conn


def add_user(conn, name):
    cursor = conn.execute("INSERT INTO users (name) VALUES (?)", (name,))
    conn.commit()
    return cursor.lastrowid


def find_users(conn, prefix):
    query = f"SELECT id, name FROM users WHERE name LIKE '{prefix}%' ORDER BY name"
    return conn.execute(query).fetchall()
''',
    "app.py": r'''from flask import Flask, jsonify, request

import db

app = Flask(__name__)


def get_conn():
    return db.connect()


@app.post("/users")
def create_user():
    name = request.get_json()["name"]
    user_id = db.add_user(get_conn(), name)
    return jsonify({"id": user_id, "name": name}), 201
''',
}

B3_CHECK = r'''
import os
if os.path.exists("app.db"):
    os.remove("app.db")
import db
from app import app

conn = db.connect(":memory:")
for name in ["alice", "alan", "bob"]:
    db.add_user(conn, name)
assert [row[1] for row in db.find_users(conn, "al")] == ["alan", "alice"]
assert [row[1] for row in db.find_users(conn, "")] == ["alan", "alice", "bob"]
assert db.find_users(conn, "' OR 1=1 --") == [], "injection returned rows"
assert db.find_users(conn, "%' OR name LIKE '%") == [], "injection returned rows"
assert db.find_users(conn, "zed") == []

c = app.test_client()
for name in ["carol", "cathy", "dave"]:
    assert c.post("/users", json={"name": name}).status_code == 201
r = c.get("/users/search?prefix=ca")
assert r.status_code == 200
body = r.get_json()
assert [u["name"] for u in body] == ["carol", "cathy"], body
assert all(set(u) == {"id", "name"} and isinstance(u["id"], int) for u in body), body
assert c.get("/users/search?prefix=x").get_json() == []
assert c.get("/users/search?prefix=' OR 1=1 --").get_json() == []
r = c.get("/users/search")
assert r.status_code == 400 and isinstance(r.get_json().get("error"), str)
'''


def b3_solution_files():
    db_text = B3_FILES["db.py"].replace(
        '''    query = f"SELECT id, name FROM users WHERE name LIKE '{prefix}%' ORDER BY name"
    return conn.execute(query).fetchall()''',
        '''    query = "SELECT id, name FROM users WHERE name LIKE ? || '%' ORDER BY name"
    return conn.execute(query, (prefix,)).fetchall()''',
    )
    app_text = B3_FILES["app.py"] + r'''

@app.get("/users/search")
def search_users():
    prefix = request.args.get("prefix")
    if prefix is None:
        return jsonify({"error": "prefix is required"}), 400
    rows = db.find_users(get_conn(), prefix)
    return jsonify([{"id": row[0], "name": row[1]} for row in rows])
'''
    return db_text, app_text


def check_b3(root, reply):
    return run_python(root, "-c", B3_CHECK).returncode == 0


def solve_b3(root):
    db_text, app_text = b3_solution_files()
    write(root, "db.py", db_text)
    write(root, "app.py", app_text)
    return "Fixed the injection and added the search endpoint."


# ---------- b4: add token authentication ----------

B4_FILES = {
    "app.py": r'''from flask import Flask, jsonify

app = Flask(__name__)
app.config["API_TOKEN"] = None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/admin/stats")
def stats():
    return jsonify({"users": 3})


@app.delete("/admin/users/<int:user_id>")
def delete_user(user_id):
    return "", 204
''',
}

B4_CHECK = r'''
from app import app
c = app.test_client()
app.config["API_TOKEN"] = "s3cret"


def auth(value):
    return {"Authorization": value}


assert c.get("/health").status_code == 200
r = c.get("/admin/stats")
assert r.status_code == 401 and r.get_json() == {"error": "unauthorized"}, r.data
assert c.get("/admin/stats", headers=auth("Bearer wrong")).status_code == 401
assert c.get("/admin/stats", headers=auth("Basic s3cret")).status_code == 401
assert c.get("/admin/stats", headers=auth("s3cret")).status_code == 401
r = c.get("/admin/stats", headers=auth("Bearer s3cret"))
assert r.status_code == 200 and r.get_json() == {"users": 3}
assert c.delete("/admin/users/1").status_code == 401
assert c.delete("/admin/users/1", headers=auth("Bearer s3cret")).status_code == 204

app.config["API_TOKEN"] = "other"
assert c.get("/admin/stats", headers=auth("Bearer s3cret")).status_code == 401
assert c.get("/admin/stats", headers=auth("Bearer other")).status_code == 200

for empty in (None, ""):
    app.config["API_TOKEN"] = empty
    for header in ("Bearer None", "Bearer ", "Bearer"):
        assert c.get("/admin/stats", headers=auth(header)).status_code == 401, (empty, header)
assert c.get("/health").status_code == 200
'''


def b4_solution() -> str:
    return B4_FILES["app.py"].replace("from flask import Flask, jsonify", "from flask import Flask, jsonify, request") + r'''

@app.before_request
def require_token():
    if not request.path.startswith("/admin"):
        return None
    token = app.config.get("API_TOKEN")
    if token and request.headers.get("Authorization", "") == f"Bearer {token}":
        return None
    return jsonify({"error": "unauthorized"}), 401
'''


def check_b4(root, reply):
    return run_python(root, "-c", B4_CHECK).returncode == 0


def solve_b4(root):
    write(root, "app.py", b4_solution())
    return "Added token authentication to the admin routes."


# ---------- b5: fix pagination bugs found by failing tests ----------

B5_TESTS = r'''import unittest

from app import app


class PaginationTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def ids(self, query):
        response = self.client.get("/items" + query)
        return [item["id"] for item in response.get_json()["items"]]

    def test_first_page(self):
        self.assertEqual(self.ids("?page=1&per_page=3"), [1, 2, 3])

    def test_last_page(self):
        self.assertEqual(self.ids("?page=3&per_page=3"), [7])

    def test_beyond_last_page(self):
        self.assertEqual(self.ids("?page=9&per_page=3"), [])

    def test_total_is_reported(self):
        response = self.client.get("/items?page=1&per_page=2")
        self.assertEqual(response.get_json()["total"], 7)

    def test_bad_page_value(self):
        self.assertEqual(self.client.get("/items?page=abc").status_code, 400)
        self.assertEqual(self.client.get("/items?page=0").status_code, 400)

    def test_bad_per_page_value(self):
        self.assertEqual(self.client.get("/items?per_page=0").status_code, 400)
        self.assertEqual(self.client.get("/items?per_page=-2").status_code, 400)
'''
B5_FILES = {
    "app.py": r'''from flask import Flask, jsonify, request

app = Flask(__name__)
ITEMS = [{"id": n, "name": f"item{n}"} for n in range(1, 8)]


@app.get("/items")
def list_items():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 3))
    start = page * per_page
    end = start + per_page
    return jsonify({"items": ITEMS[start:end], "total": len(ITEMS)})
''',
    "test_app.py": B5_TESTS,
}

B5_SOLUTION = r'''from flask import Flask, jsonify, request

app = Flask(__name__)
ITEMS = [{"id": n, "name": f"item{n}"} for n in range(1, 8)]


def positive_int(name, default):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@app.get("/items")
def list_items():
    page = positive_int("page", 1)
    per_page = positive_int("per_page", 3)
    if page is None or per_page is None:
        return jsonify({"error": "page and per_page must be positive integers"}), 400
    start = (page - 1) * per_page
    return jsonify({"items": ITEMS[start:start + per_page], "total": len(ITEMS)})
'''


def check_b5(root, reply):
    return read(root, "test_app.py") == B5_TESTS and unittest_passes(root, 6)


def solve_b5(root):
    write(root, "app.py", B5_SOLUTION)
    return "Fixed the pagination."


# ---------- b6: write tests that catch bugs ----------

B6_APP = r'''from flask import Flask, jsonify, request

app = Flask(__name__)


@app.post("/add")
def add():
    data = request.get_json()
    return jsonify({"result": data["a"] + data["b"]})


@app.post("/divide")
def divide():
    data = request.get_json()
    if data["b"] == 0:
        return jsonify({"error": "division by zero"}), 400
    return jsonify({"result": data["a"] / data["b"]})
'''

# Each mutant is a small bug. Good tests fail on every one of them.
B6_MUTANTS = [
    ('data["a"] + data["b"]', 'data["a"] - data["b"]'),
    ('if data["b"] == 0:', "if False:"),
    ('data["a"] / data["b"]', 'data["a"] * data["b"]'),
    ('"division by zero"}), 400', '"division by zero"}), 200'),
]

B6_SOLUTION_TESTS = r'''import unittest

from app import app


class CalculatorTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_add(self):
        response = self.client.post("/add", json={"a": 2, "b": 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"result": 5})

    def test_add_negative(self):
        response = self.client.post("/add", json={"a": -2, "b": 1})
        self.assertEqual(response.get_json(), {"result": -1})

    def test_divide(self):
        response = self.client.post("/divide", json={"a": 9, "b": 2})
        self.assertEqual(response.get_json(), {"result": 4.5})

    def test_divide_by_zero(self):
        response = self.client.post("/divide", json={"a": 1, "b": 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "division by zero"})
'''


def check_b6(root, reply):
    if read(root, "app.py") != B6_APP:
        return False
    if not unittest_passes(root, at_least=3):
        return False
    for old, new in B6_MUTANTS:
        with tempfile.TemporaryDirectory() as mutant:
            shutil.copytree(root, mutant, dirs_exist_ok=True)
            write(mutant, "app.py", B6_APP.replace(old, new, 1))
            if run_python(mutant, "-m", "unittest").returncode == 0:
                return False
    return True


def solve_b6(root):
    write(root, "test_app.py", B6_SOLUTION_TESTS)
    return "Wrote tests for both endpoints."


# ---------- b7: build a package with an app factory from a spec ----------

B7_CHECK = r'''
from bookshop import create_app

a = create_app({"TESTING": True})
b = create_app()
ca, cb = a.test_client(), b.test_client()
assert a.config["TESTING"] is True


def book(title, author, price):
    return {"title": title, "author": author, "price": price}


r = ca.post("/books", json=book("Dune", "Frank Herbert", 9.5))
assert r.status_code == 201, r.status_code
dune = r.get_json()
assert isinstance(dune["id"], int) and dune["title"] == "Dune" and dune["price"] == 9.5, dune
assert ca.post("/books", json=book("Emma", "Jane Austen", 5)).status_code == 201
assert ca.post("/books", json=book("Persuasion", "jane austen", 12)).status_code == 201

assert cb.get("/books").get_json() == [], "apps share data"
assert len(ca.get("/books").get_json()) == 3

def titles(response):
    return {x["title"] for x in response.get_json()}

assert titles(ca.get("/books?author=JANE AUSTEN")) == {"Emma", "Persuasion"}
assert titles(ca.get("/books?max_price=9.5")) == {"Dune", "Emma"}
assert titles(ca.get("/books?author=jane austen&max_price=6")) == {"Emma"}
assert ca.get("/books?author=nobody").get_json() == []

r = ca.get(f"/books/{dune['id']}")
assert r.status_code == 200 and r.get_json()["author"] == "Frank Herbert"
r = ca.get("/books/9999")
assert r.status_code == 404 and r.get_json() == {"error": "not found"}, r.data

r = ca.put(f"/books/{dune['id']}", json=book("Dune Messiah", "Frank Herbert", 11))
assert r.status_code == 200, r.status_code
assert r.get_json()["title"] == "Dune Messiah" and r.get_json()["id"] == dune["id"]
assert ca.get(f"/books/{dune['id']}").get_json()["price"] == 11
assert ca.put(f"/books/{dune['id']}", json={"title": "x"}).status_code == 422

bad_books = [
    {}, book("", "a", 1), book("t", "", 1), book("t", "a", -1), book("t", "a", "5"), book(1, "a", 1),
]
for bad in bad_books:
    r = ca.post("/books", json=bad)
    assert r.status_code == 422, (bad, r.status_code)
    assert isinstance(r.get_json().get("error"), str), bad
assert ca.post("/books", json=book("Free", "a", 0)).status_code == 201

assert ca.delete(f"/books/{dune['id']}").status_code == 204
assert ca.get(f"/books/{dune['id']}").status_code == 404
assert len(ca.get("/books").get_json()) == 3
'''

B7_SOLUTION = r'''from flask import Flask, jsonify, request


def create_app(config=None):
    app = Flask(__name__)
    if config:
        app.config.update(config)
    books = {}
    counter = {"next": 1}

    def error(message, status):
        return jsonify({"error": message}), status

    def read_book():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, "a JSON object is required"
        title, author, price = data.get("title"), data.get("author"), data.get("price")
        if not isinstance(title, str) or not title:
            return None, "title must be a non-empty string"
        if not isinstance(author, str) or not author:
            return None, "author must be a non-empty string"
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
            return None, "price must be a number that is zero or more"
        return {"title": title, "author": author, "price": price}, None

    @app.post("/books")
    def create_book():
        fields, problem = read_book()
        if problem:
            return error(problem, 422)
        book = {"id": counter["next"], **fields}
        books[book["id"]] = book
        counter["next"] += 1
        return jsonify(book), 201

    @app.get("/books")
    def list_books():
        result = list(books.values())
        author = request.args.get("author")
        if author is not None:
            result = [b for b in result if b["author"].lower() == author.lower()]
        max_price = request.args.get("max_price")
        if max_price is not None:
            try:
                limit = float(max_price)
            except ValueError:
                return error("max_price must be a number", 400)
            result = [b for b in result if b["price"] <= limit]
        return jsonify(result)

    @app.get("/books/<int:book_id>")
    def get_book(book_id):
        book = books.get(book_id)
        return jsonify(book) if book else error("not found", 404)

    @app.put("/books/<int:book_id>")
    def replace_book(book_id):
        if book_id not in books:
            return error("not found", 404)
        fields, problem = read_book()
        if problem:
            return error(problem, 422)
        books[book_id] = {"id": book_id, **fields}
        return jsonify(books[book_id])

    @app.delete("/books/<int:book_id>")
    def delete_book(book_id):
        if books.pop(book_id, None) is None:
            return error("not found", 404)
        return "", 204

    return app
'''


def check_b7(root, reply):
    return run_python(root, "-c", B7_CHECK).returncode == 0


def solve_b7(root):
    write(root, "bookshop/__init__.py", B7_SOLUTION)
    return "Created the bookshop package."


B1_SPEC = (
         "Create app.py with a Flask API for a todo list. The Flask app must be named `app`. "
         "Keep the todos in memory.\n"
         "- POST /todos takes JSON {\"title\": str}. It returns 201 with {\"id\": int, \"title\": str, \"done\": false}. "
         "A missing, empty, or blank title returns 400 with {\"error\": str}.\n"
         "- GET /todos returns the list of todos.\n"
         "- GET /todos/<id> returns one todo, or 404 with {\"error\": str}.\n"
         "- PATCH /todos/<id> takes JSON with an optional title and done, updates the todo, and returns it. "
         "It returns 404 for an unknown id.\n"
         "- DELETE /todos/<id> returns 204 with no body. It returns 404 for an unknown id."
)

# ---------- the task list ----------

BACKEND = [
    Task("b1_flask_todo_api", "backend", B1_SPEC + SERVER_NOTE,
         {}, check_b1, solve_b1, detail=detail_b1),
    Task("b2_validate_and_json_404", "backend",
         "Add input validation to POST /items in app.py. The name must be a non-empty string. "
         "The price must be a positive number, and a boolean does not count as a number. "
         "For invalid input, return status 422 with JSON {\"error\": \"<message>\"}. "
         "Also make unknown routes return JSON {\"error\": \"not found\"} with status 404, not an HTML page. "
         "The existing tests must still pass." + SERVER_NOTE,
         B2_FILES, check_b2, solve_b2),
    Task("b3_sql_injection_and_search", "backend",
         "The user search in db.py has a security problem. Fix it. "
         "Then add GET /users/search?prefix=<text> to app.py. "
         "It returns a JSON list of {\"id\": int, \"name\": str} for users whose name starts with the prefix, "
         "sorted by name. A request without a prefix returns 400 with {\"error\": str}." + SERVER_NOTE,
         B3_FILES, check_b3, solve_b3),
    Task("b4_token_auth", "backend",
         "Add token authentication to app.py. Every route whose path starts with /admin must require the header "
         "`Authorization: Bearer <token>`, where <token> is the current value of app.config[\"API_TOKEN\"]. "
         "Read it on every request. A missing or wrong token returns 401 with {\"error\": \"unauthorized\"}. "
         "If API_TOKEN is not set (None or empty), reject every /admin request, even one with a header. "
         "/health stays public. Do not change what the routes return when the token is right." + SERVER_NOTE,
         B4_FILES, check_b4, solve_b4),
    Task("b5_fix_pagination", "backend",
         "The tests in test_app.py fail. Run them, find the bugs in app.py, and fix them. "
         "Do not change the tests.",
         B5_FILES, check_b5, solve_b5),
    Task("b6_write_tests", "backend",
         "Write unit tests for app.py in a new file test_app.py. Use unittest and Flask's test client. "
         "Cover both endpoints, including the error case. Do not change app.py.",
         {"app.py": B6_APP}, check_b6, solve_b6),
    Task("b7_bookshop_package", "backend",
         "Create a Flask API for a bookshop as a package named `bookshop`.\n"
         "- bookshop/__init__.py defines create_app(config=None), an app factory. "
         "config is an optional dict that is applied to app.config.\n"
         "- Books live in memory, per app. Two apps from create_app must not share data.\n"
         "- POST /books takes JSON {\"title\": str, \"author\": str, \"price\": number}. "
         "Title and author must be non-empty strings. Price must be a number that is zero or more. "
         "It returns 201 with the book plus an integer id. Invalid input returns 422 with {\"error\": str}.\n"
         "- GET /books returns the list. ?author=<name> filters by exact author, ignoring case. "
         "?max_price=<number> keeps books at or under that price. The two filters can be combined.\n"
         "- GET /books/<id> returns the book, or 404 with {\"error\": \"not found\"}.\n"
         "- PUT /books/<id> replaces the title, author, and price with the same validation, and returns the book. "
         "It returns 404 for an unknown id.\n"
         "- DELETE /books/<id> returns 204 with no body." + SERVER_NOTE,
         {}, check_b7, solve_b7),
]


# ---------- variants of b1: what happens when we tell the model more? ----------
# The hidden probe is the same for all three, so the scores are comparable.
# The visible tests cover only what the spec states. The cases it leaves out stay hidden.

B1_VISIBLE_TESTS = r"""import unittest

from app import app


class TodoTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def create(self, title="write tests"):
        response = self.client.post("/todos", json={"title": title})
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def test_create_returns_the_new_todo(self):
        todo = self.create("buy milk")
        self.assertEqual(todo["title"], "buy milk")
        self.assertIs(todo["done"], False)
        self.assertIsInstance(todo["id"], int)

    def test_each_todo_gets_its_own_id(self):
        self.assertNotEqual(self.create("one")["id"], self.create("two")["id"])

    def test_missing_title_is_rejected(self):
        response = self.client.post("/todos", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.get_json()["error"], str)

    def test_empty_title_is_rejected(self):
        response = self.client.post("/todos", json={"title": ""})
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.get_json()["error"], str)

    def test_blank_title_is_rejected(self):
        response = self.client.post("/todos", json={"title": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.get_json()["error"], str)

    def test_list_includes_created_todos(self):
        todo = self.create("listed")
        response = self.client.get("/todos")
        self.assertEqual(response.status_code, 200)
        self.assertIn(todo["id"], [item["id"] for item in response.get_json()])

    def test_get_one_todo(self):
        todo = self.create("fetch me")
        response = self.client.get(f"/todos/{todo['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "fetch me")

    def test_get_unknown_todo_is_404(self):
        response = self.client.get("/todos/9999")
        self.assertEqual(response.status_code, 404)
        self.assertIsInstance(response.get_json()["error"], str)

    def test_patch_done_keeps_the_title(self):
        todo = self.create("finish")
        response = self.client.patch(f"/todos/{todo['id']}", json={"done": True})
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.get_json()["done"], True)
        self.assertEqual(response.get_json()["title"], "finish")

    def test_patch_title_keeps_done(self):
        todo = self.create("old")
        self.client.patch(f"/todos/{todo['id']}", json={"done": True})
        response = self.client.patch(f"/todos/{todo['id']}", json={"title": "new"})
        self.assertEqual(response.get_json()["title"], "new")
        self.assertIs(response.get_json()["done"], True)

    def test_patch_is_saved(self):
        todo = self.create("persist")
        self.client.patch(f"/todos/{todo['id']}", json={"done": True})
        self.assertIs(self.client.get(f"/todos/{todo['id']}").get_json()["done"], True)

    def test_patch_unknown_todo_is_404(self):
        self.assertEqual(self.client.patch("/todos/9999", json={"done": True}).status_code, 404)

    def test_delete_returns_204_with_no_body(self):
        todo = self.create("remove")
        response = self.client.delete(f"/todos/{todo['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")

    def test_deleted_todo_is_gone(self):
        todo = self.create("gone")
        self.client.delete(f"/todos/{todo['id']}")
        self.assertEqual(self.client.get(f"/todos/{todo['id']}").status_code, 404)
        ids = [item["id"] for item in self.client.get("/todos").get_json()]
        self.assertNotIn(todo["id"], ids)

    def test_delete_unknown_todo_is_404(self):
        self.assertEqual(self.client.delete("/todos/9999").status_code, 404)
"""
B1_VISIBLE_TEST_COUNT = 15

# Cases the spec does not state. They stay hidden in every variant.
B1_HIDDEN_ONLY = {
    "06 null title returns 400 with an error",
    "07 a non-string title does not crash",
    "08 a non-JSON body does not crash",
}

VISIBLE_TESTS_NOTE = (
    " The file test_todos.py has tests for the behavior above. "
    "Run them with `python -m unittest` and make them pass. Do not change the tests."
)
VALIDATE_NOTE = " Validate all input. Never return a 500 for bad input."
OWN_TESTS_NOTE = (
    " Before you finish, write your own tests for the edge cases a client could send. "
    "Put them in test_app.py, run them with `python -m unittest`, and make them pass."
)


def detail_b1_visible_tests(root, reply):
    detail = detail_b1(root, reply)
    detail["20 the visible tests are unchanged"] = read(root, "test_todos.py") == B1_VISIBLE_TESTS
    detail["21 the visible tests pass"] = unittest_passes(root, at_least=B1_VISIBLE_TEST_COUNT)
    return detail


def check_b1_visible_tests(root, reply):
    return all(detail_b1_visible_tests(root, reply).values())


def detail_b1_own_tests(root, reply):
    detail = detail_b1(root, reply)
    detail["20 its own tests exist and pass"] = read(root, "test_app.py") != "" and unittest_passes(root, at_least=1)
    return detail


def check_b1_own_tests(root, reply):
    return all(detail_b1_own_tests(root, reply).values())


def solve_b1_own_tests(root):
    write(root, "app.py", B1_SOLUTION)
    write(root, "test_app.py", (
        "import unittest\n\nfrom app import app\n\n\nclass T(unittest.TestCase):\n"
        "    def test_bad_title_is_rejected(self):\n"
        '        self.assertEqual(app.test_client().post("/todos", json={}).status_code, 400)\n'
    ))
    return "Created the todo API and wrote tests for it."


VARIANTS = [
    Task("b1v_visible_tests", "variant", B1_SPEC + VISIBLE_TESTS_NOTE + SERVER_NOTE,
         {"test_todos.py": B1_VISIBLE_TESTS}, check_b1_visible_tests, solve_b1,
         detail=detail_b1_visible_tests),
    Task("b1v_validate_line", "variant", B1_SPEC + VALIDATE_NOTE + SERVER_NOTE,
         {}, check_b1, solve_b1, detail=detail_b1),
    Task("b1v_write_own_tests", "variant", B1_SPEC + OWN_TESTS_NOTE + SERVER_NOTE,
         {}, check_b1_own_tests, solve_b1_own_tests, detail=detail_b1_own_tests),
]
