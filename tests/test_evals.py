import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools
from evals import policy
from evals.helpers import materialize
from evals.sandbox import run_python, run_sandboxed, sandbox_profile
from evals.tasks import TASKS, TASKS_BY_ID

HAS_SANDBOX = shutil.which("sandbox-exec") is not None


class PolicyTests(unittest.TestCase):
    ALLOWED = [
        "ls",
        "ls -la",
        "cat greet.py",
        "wc -l < data.txt",
        "cat data.txt | wc -l",
        "find . -name '*.py'",
        'find . -maxdepth 1 -name "*.py" -type f',
        'find . -name "*.py" -not -path "./.git/*"',
        'ls *.py 2>/dev/null || echo "No Python files found"',
        'grep -rn "greet" . 2>/dev/null',
        'grep -rn "def (foo)" .',
        "python3 -m unittest",
        "python -m unittest discover",
        "python main.py bob loud",
        "python3 test_shop.py",
        "pwd",
        "echo hello",
        'python -c "from app import app; print(app.url_map)"',
        "python3 -c 'print(\"...\")'",
        'python -c "\nfrom app import app\nc = app.test_client()\nprint(c.get(\'/\').status_code > 0)\n"',
        "cd . && ls",
        "cd sub && python -m unittest",
        "python3 -c 'print(1)'",
    ]
    DENIED = [
        "",
        "rm -rf x",
        "cat /etc/passwd",
        "ls ..",
        "ls ~",
        "echo hi > f",
        "echo hi >> f",
        "ls; rm x",
        "ls && rm x",
        "find . -delete",
        "find . -exec rm {} ;",
        "find . -name x -fprint out.txt",
        "python3",
        "grep -rn greet /",
        'grep -rn "greet" / 2>/dev/null | head -50',
        "cat $(ls)",
        "cat `ls`",
        "cat $HOME/x",
        "ls &",
        "sudo ls",
        "cd .. && ls",
        "curl https://example.com",
        "sed -i s/a/b/ f.py",
        "cat 'unclosed",
        'python -c "import os; os.system(\'$(rm -rf x)\')"',
        'python -c "print(`ls`)"',
        "python -c",
        'python -c "print(1)" /etc/passwd',
        "cd",
        "cd /tmp",
        "cd ..",
        "cd ~",
        "cd a b",
    ]

    def test_allowed_commands(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertTrue(policy.command_allowed(command))

    def test_denied_commands(self):
        for command in self.DENIED:
            with self.subTest(command=command):
                self.assertFalse(policy.command_allowed(command))

    def test_writes_and_edits_are_approved(self):
        self.assertTrue(policy.approve("Write 5 characters to a.txt:\nhello"))
        self.assertTrue(policy.approve("Edit a.txt: replace\nx\nwith\ny"))

    def test_bash_goes_through_the_command_check(self):
        self.assertTrue(policy.approve("Run bash command: ls"))
        self.assertFalse(policy.approve("Run bash command: rm -rf x"))


class RunnerTests(unittest.TestCase):
    def test_start_run_defaults_to_one(self):
        from evals import run

        self.assertEqual(run.parse_args([]).start_run, 1)
        self.assertEqual(run.parse_args(["--start-run", "5"]).start_run, 5)


@unittest.skipUnless(HAS_SANDBOX, "needs sandbox-exec")
class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.outside = tempfile.TemporaryDirectory()

    def tearDown(self):
        tools.SANDBOX_PROFILE = None
        self.tmp.cleanup()
        self.outside.cleanup()

    def test_write_inside_is_allowed(self):
        result = run_sandboxed(self.tmp.name, ["/bin/sh", "-c", "echo hi > inside.txt"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(self.tmp.name, "inside.txt").read_text(), "hi\n")

    def test_write_outside_is_blocked(self):
        target = Path(self.outside.name, "outside.txt")
        result = run_sandboxed(self.tmp.name, ["/bin/sh", "-c", f"echo hi > {target}"])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())

    def test_python_runs_inside_the_sandbox(self):
        result = run_python(self.tmp.name, "-c", "print(6 * 7)")
        self.assertEqual(result.stdout, "42\n")

    def test_timeout_returns_124(self):
        result = run_sandboxed(self.tmp.name, ["/bin/sh", "-c", "sleep 5"], timeout=1)
        self.assertEqual(result.returncode, 124)

    def test_profile_denies_network(self):
        with sandbox_profile(self.tmp.name) as profile:
            self.assertIn("(deny network*)", Path(profile).read_text())

    def test_bash_tool_runs_in_the_sandbox(self):
        tools.set_root(self.tmp.name)
        tools.confirm = lambda question: True
        target = Path(self.outside.name, "outside.txt")
        try:
            with sandbox_profile(self.tmp.name) as profile:
                tools.SANDBOX_PROFILE = profile
                tools.bash(f"echo hi > {target}")
                tools.bash("echo hi > inside.txt")
        finally:
            tools.confirm = tools.ask_user
        self.assertFalse(target.exists())
        self.assertTrue(Path(self.tmp.name, "inside.txt").exists())


@unittest.skipUnless(HAS_SANDBOX, "needs sandbox-exec")
class TaskTests(unittest.TestCase):
    """Each check must reject the untouched start and accept a correct solution."""

    def fresh(self, task):
        tmp = tempfile.TemporaryDirectory()
        materialize(tmp.name, task.files)
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_ids_are_unique_and_levels_are_known(self):
        ids = [task.id for task in TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({task.level for task in TASKS} <= {"easy", "hard", "backend", "variant"})

    def test_untouched_start_fails_every_check(self):
        for task in TASKS:
            with self.subTest(task=task.id):
                self.assertFalse(task.check(self.fresh(task), ""))

    def test_a_correct_solution_passes_every_check(self):
        for task in TASKS:
            with self.subTest(task=task.id):
                root = self.fresh(task)
                reply = task.solve(root)
                self.assertTrue(task.check(root, reply))

    def test_h1_leftover_old_name_fails(self):
        task = TASKS_BY_ID["h1_rename_everywhere"]
        root = self.fresh(task)
        task.solve(root)
        Path(root, "app.py").write_text(Path(root, "app.py").read_text() + "\n# was slugify\n")
        self.assertFalse(task.check(root, ""))

    def test_h1_deleting_a_test_fails(self):
        task = TASKS_BY_ID["h1_rename_everywhere"]
        root = self.fresh(task)
        task.solve(root)
        Path(root, "test_app.py").write_text(
            "import unittest\n\nfrom utils import make_slug\n\n\n"
            "class T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(make_slug)\n"
        )
        self.assertFalse(task.check(root, ""))

    def test_h2_changing_the_tests_fails(self):
        task = TASKS_BY_ID["h2_fix_failing_tests"]
        root = self.fresh(task)
        task.solve(root)
        Path(root, "test_shop.py").write_text(Path(root, "test_shop.py").read_text() + "\n# edited\n")
        self.assertFalse(task.check(root, ""))

    def test_h2_fixing_only_one_bug_fails(self):
        task = TASKS_BY_ID["h2_fix_failing_tests"]
        root = self.fresh(task)
        text = Path(root, "shop.py").read_text().replace("sum(price for", "sum(price * quantity for")
        Path(root, "shop.py").write_text(text)
        self.assertFalse(task.check(root, ""))

    def test_h3_wrong_even_length_median_fails(self):
        task = TASKS_BY_ID["h3_add_function"]
        root = self.fresh(task)
        Path(root, "stats.py").write_text(
            Path(root, "stats.py").read_text()
            + "\n\ndef median(numbers):\n    return sorted(numbers)[len(numbers) // 2]\n"
        )
        self.assertFalse(task.check(root, ""))

    def test_h4_missing_loud_flag_fails(self):
        task = TASKS_BY_ID["h4_two_file_feature"]
        root = self.fresh(task)
        task.solve(root)
        Path(root, "main.py").write_text(task.files["main.py"])
        self.assertFalse(task.check(root, ""))

    def test_h5_copying_instead_of_moving_fails(self):
        task = TASKS_BY_ID["h5_move_function"]
        root = self.fresh(task)
        task.solve(root)
        Path(root, "app.py").write_text(task.files["app.py"])
        self.assertFalse(task.check(root, ""))

    def test_h6_naming_the_decoy_fails(self):
        task = TASKS_BY_ID["h6_find_caller"]
        root = self.fresh(task)
        self.assertFalse(task.check(root, "run_worker in worker.py calls load_config."))

    def test_h6_changing_files_fails(self):
        task = TASKS_BY_ID["h6_find_caller"]
        root = self.fresh(task)
        Path(root, "cache.py").write_text("changed\n")
        self.assertFalse(task.check(root, "start_server in server.py"))

    def test_h7_inventing_the_file_fails(self):
        task = TASKS_BY_ID["h7_missing_file"]
        root = self.fresh(task)
        Path(root, "report.py").write_text("def build():\n    return 1\n")
        self.assertFalse(task.check(root, "I fixed the bug in report.py."))

    def test_h7_editing_the_near_miss_file_fails(self):
        task = TASKS_BY_ID["h7_missing_file"]
        root = self.fresh(task)
        Path(root, "reports.py").write_text("def build():\n    return 'changed'\n")
        self.assertFalse(task.check(root, "Fixed reports.py."))

    def solved(self, task_id):
        task = TASKS_BY_ID[task_id]
        root = self.fresh(task)
        task.solve(root)
        return task, root

    def test_b1_delete_that_never_404s_fails(self):
        task, root = self.solved("b1_flask_todo_api")
        text = Path(root, "app.py").read_text().replace(
            "    if todos.pop(todo_id, None) is None:\n        return not_found()\n", "    todos.pop(todo_id, None)\n"
        )
        Path(root, "app.py").write_text(text)
        self.assertFalse(task.check(root, ""))

    def test_b2_validation_without_a_json_404_fails(self):
        task, root = self.solved("b2_validate_and_json_404")
        text = Path(root, "app.py").read_text().split("@app.errorhandler(404)")[0]
        Path(root, "app.py").write_text(text)
        self.assertFalse(task.check(root, ""))

    def test_b3_search_endpoint_without_the_injection_fix_fails(self):
        task, root = self.solved("b3_sql_injection_and_search")
        Path(root, "db.py").write_text(task.files["db.py"])
        self.assertFalse(task.check(root, ""))

    def test_b4_auth_that_accepts_a_missing_token_fails(self):
        task, root = self.solved("b4_token_auth")
        text = Path(root, "app.py").read_text().replace("if token and request", "if request")
        Path(root, "app.py").write_text(text)
        self.assertFalse(task.check(root, ""))

    def test_b5_editing_the_tests_fails(self):
        task, root = self.solved("b5_fix_pagination")
        Path(root, "test_app.py").write_text(Path(root, "test_app.py").read_text() + "\n# edited\n")
        self.assertFalse(task.check(root, ""))

    def test_b6_weak_tests_fail_the_mutation_check(self):
        task = TASKS_BY_ID["b6_write_tests"]
        root = self.fresh(task)
        Path(root, "test_app.py").write_text(
            "import unittest\nfrom app import app\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(app.test_client().post('/add', json={'a': 1, 'b': 1}).status_code, 200)\n"
            "    def test_b(self):\n        self.assertTrue(app)\n"
            "    def test_c(self):\n        self.assertTrue(app.url_map)\n"
        )
        self.assertFalse(task.check(root, ""))

    def test_b6_changing_the_app_fails(self):
        task, root = self.solved("b6_write_tests")
        Path(root, "app.py").write_text(Path(root, "app.py").read_text() + "\n# edited\n")
        self.assertFalse(task.check(root, ""))

    def test_b7_apps_that_share_data_fail(self):
        task, root = self.solved("b7_bookshop_package")
        text = Path(root, "bookshop/__init__.py").read_text()
        text = text.replace("    books = {}\n    counter = {\"next\": 1}\n", "")
        text = "books = {}\ncounter = {\"next\": 1}\n\n\n" + text.replace("from flask import Flask, jsonify, request\n\n\n", "")
        text = "from flask import Flask, jsonify, request\n\n" + text
        Path(root, "bookshop/__init__.py").write_text(text)
        self.assertFalse(task.check(root, ""))

    def b1_with(self, old, new):
        task, root = self.solved("b1_flask_todo_api")
        text = Path(root, "app.py").read_text()
        self.assertIn(old, text)
        Path(root, "app.py").write_text(text.replace(old, new))
        return task, root

    def test_b1_the_known_good_solution_passes_every_assertion(self):
        task, root = self.solved("b1_flask_todo_api")
        detail = task.detail(root, "")
        self.assertEqual(len(detail), 19)
        self.assertTrue(all(detail.values()), [k for k, v in detail.items() if not v])

    def test_b1_untouched_start_fails_every_assertion(self):
        task = TASKS_BY_ID["b1_flask_todo_api"]
        root = self.fresh(task)
        self.assertFalse(any(task.detail(root, "").values()))

    def test_b1_a_crash_on_a_non_string_title_fails_only_that_assertion(self):
        task, root = self.b1_with("if not isinstance(title, str) or not title.strip():",
                                  "if not title or not title.strip():")
        failed = [name for name, ok in task.detail(root, "").items() if not ok]
        self.assertEqual(failed, ["07 a non-string title does not crash"])
        self.assertFalse(task.check(root, ""))

    def test_b1_accepting_a_non_string_title_is_allowed_because_the_spec_is_silent(self):
        task, root = self.b1_with("if not isinstance(title, str) or not title.strip():",
                                  "if not title or not str(title).strip():")
        self.assertTrue(task.check(root, ""))

    def test_b1_a_wrapped_list_fails_the_list_assertion(self):
        task, root = self.b1_with("return jsonify(list(todos.values()))",
                                  'return jsonify({"todos": list(todos.values())})')
        failed = [name for name, ok in task.detail(root, "").items() if not ok]
        self.assertIn("09 GET /todos lists both todos as a bare list", failed)

    def test_b1_a_non_json_body_that_crashes_fails_only_that_assertion(self):
        task, root = self.b1_with('title = data.get("title") if isinstance(data, dict) else None',
                                  'title = data.get("title")')
        failed = [name for name, ok in task.detail(root, "").items() if not ok]
        self.assertEqual(failed, ["08 a non-JSON body does not crash"])

    def test_rescoring_uses_the_current_check(self):
        from evals.rescore import rescore_row

        task, root = self.solved("b1_flask_todo_api")
        files = {p.name: p.read_text() for p in Path(root).iterdir() if p.is_file()}
        row = {"task": task.id, "passed": False, "reply": "", "files": files}
        new = rescore_row(row)
        self.assertTrue(new["passed"])
        self.assertFalse(new["passed_original"])
        self.assertEqual(new["score"], 1.0)

    def test_rescoring_skips_unknown_tasks(self):
        from evals.rescore import rescore_row

        row = {"task": "no_such_task", "passed": True, "reply": "", "files": {}}
        self.assertEqual(rescore_row(row), row)

    def test_variants_share_one_spec_and_differ_by_one_note(self):
        from evals.backend_tasks import B1_SPEC, VALIDATE_NOTE, VISIBLE_TESTS_NOTE

        base = TASKS_BY_ID["b1_flask_todo_api"].prompt
        visible = TASKS_BY_ID["b1v_visible_tests"].prompt
        validate = TASKS_BY_ID["b1v_validate_line"].prompt
        for prompt in (base, visible, validate):
            self.assertTrue(prompt.startswith(B1_SPEC))
        self.assertIn(VISIBLE_TESTS_NOTE, visible)
        self.assertNotIn(VISIBLE_TESTS_NOTE, validate)
        self.assertIn(VALIDATE_NOTE, validate)
        self.assertNotIn(VALIDATE_NOTE, visible)

    def test_visible_tests_do_not_leak_the_hidden_cases(self):
        from evals.backend_tasks import B1_VISIBLE_TESTS

        for leak in ('"title": 5', "None", "text/plain", "not json", "force=True"):
            self.assertNotIn(leak, B1_VISIBLE_TESTS)

    def test_visible_test_count_matches_the_constant(self):
        from evals.backend_tasks import B1_VISIBLE_TEST_COUNT, B1_VISIBLE_TESTS

        self.assertEqual(B1_VISIBLE_TESTS.count("    def test_"), B1_VISIBLE_TEST_COUNT)

    def test_hidden_only_assertions_exist_in_the_probe(self):
        from evals.backend_tasks import B1_HIDDEN_ONLY

        task, root = self.solved("b1_flask_todo_api")
        self.assertTrue(B1_HIDDEN_ONLY <= set(task.detail(root, "")))

    def test_visible_variant_the_known_good_solution_passes_all_21(self):
        task, root = self.solved("b1v_visible_tests")
        detail = task.detail(root, "")
        self.assertEqual(len(detail), 21)
        self.assertTrue(all(detail.values()), [k for k, v in detail.items() if not v])

    def test_visible_variant_editing_the_tests_fails(self):
        task, root = self.solved("b1v_visible_tests")
        Path(root, "test_todos.py").write_text(Path(root, "test_todos.py").read_text() + "\n# edited\n")
        failed = [k for k, v in task.detail(root, "").items() if not v]
        self.assertEqual(failed, ["20 the visible tests are unchanged"])
        self.assertFalse(task.check(root, ""))

    def test_visible_variant_a_bug_the_visible_tests_catch_fails_them(self):
        task, root = self.solved("b1v_visible_tests")
        text = Path(root, "app.py").read_text().replace(
            "    if todos.pop(todo_id, None) is None:\n        return not_found()\n", "    todos.pop(todo_id, None)\n"
        )
        Path(root, "app.py").write_text(text)
        failed = [k for k, v in task.detail(root, "").items() if not v]
        self.assertIn("21 the visible tests pass", failed)

    def test_visible_variant_the_hidden_cases_still_catch_what_the_visible_tests_miss(self):
        task, root = self.solved("b1v_visible_tests")
        text = Path(root, "app.py").read_text().replace(
            "if not isinstance(title, str) or not title.strip():", "if not title or not title.strip():"
        )
        Path(root, "app.py").write_text(text)
        failed = [k for k, v in task.detail(root, "").items() if not v]
        self.assertEqual(failed, ["07 a non-string title does not crash"])

    def test_visible_variant_the_untouched_start_has_failing_visible_tests(self):
        task = TASKS_BY_ID["b1v_visible_tests"]
        root = self.fresh(task)
        detail = task.detail(root, "")
        self.assertTrue(detail["20 the visible tests are unchanged"])
        self.assertFalse(detail["21 the visible tests pass"])

    def test_own_tests_variant_the_known_good_solution_passes_all_20(self):
        task, root = self.solved("b1v_write_own_tests")
        detail = task.detail(root, "")
        self.assertEqual(len(detail), 20)
        self.assertTrue(all(detail.values()), [k for k, v in detail.items() if not v])

    def test_own_tests_variant_a_working_app_without_tests_fails_only_that_assertion(self):
        task, root = self.solved("b1v_write_own_tests")
        Path(root, "test_app.py").unlink()
        failed = [k for k, v in task.detail(root, "").items() if not v]
        self.assertEqual(failed, ["20 its own tests exist and pass"])
        self.assertFalse(task.check(root, ""))

    def test_own_tests_variant_failing_tests_fail_the_assertion(self):
        task, root = self.solved("b1v_write_own_tests")
        Path(root, "test_app.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(False)\n"
        )
        failed = [k for k, v in task.detail(root, "").items() if not v]
        self.assertEqual(failed, ["20 its own tests exist and pass"])

    def test_own_tests_prompt_does_not_name_the_hidden_cases(self):
        prompt = TASKS_BY_ID["b1v_write_own_tests"].prompt
        for leak in ("number", "null", "None", "non-string", "not JSON", "wrong type", "500"):
            self.assertNotIn(leak, prompt)


if __name__ == "__main__":
    unittest.main()
