import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tools.set_root(self.tmp.name)
        self.answers = []
        tools.confirm = lambda question: self.answers.pop(0) if self.answers else True

    def tearDown(self):
        tools.confirm = tools.ask_user
        tools.REQUIRE_READ_BEFORE_CHANGE = True
        self.tmp.cleanup()

    def make(self, name, text):
        Path(self.tmp.name, name).write_text(text)

    def test_write_then_read(self):
        self.assertIn("Wrote 5", tools.write_file("a.txt", "hello"))
        self.assertEqual(tools.read_file("a.txt"), "hello")

    def test_write_creates_folders(self):
        tools.write_file("sub/dir/a.txt", "x")
        self.assertEqual(tools.read_file("sub/dir/a.txt"), "x")

    def test_read_missing_file(self):
        self.assertTrue(tools.read_file("nope.txt").startswith("Error: file not found"))

    def test_read_outside_root(self):
        self.assertIn("outside the project folder", tools.read_file("../secret.txt"))

    def test_write_outside_root(self):
        self.assertIn("outside the project folder", tools.write_file("../x.txt", "x"))

    def test_read_binary_file(self):
        Path(self.tmp.name, "b.bin").write_bytes(b"\xff\xfe\x00")
        self.assertTrue(tools.read_file("b.bin").startswith("Error:"))

    def test_read_truncates(self):
        tools.write_file("big.txt", "a" * (tools.MAX_OUTPUT_CHARS + 100))
        self.assertIn("[truncated 100 characters]", tools.read_file("big.txt"))

    def test_write_denied(self):
        self.answers = [False]
        self.assertIn("denied", tools.write_file("a.txt", "x"))
        self.assertFalse(Path(self.tmp.name, "a.txt").exists())

    def test_bash_runs_in_root(self):
        tools.write_file("a.txt", "x")
        out = tools.bash("ls")
        self.assertIn("exit code: 0", out)
        self.assertIn("a.txt", out)

    def test_bash_failure(self):
        out = tools.bash("ls missing-file")
        self.assertNotIn("exit code: 0", out)
        self.assertIn("exit code:", out)

    def test_denials_include_a_hint_not_to_retry(self):
        self.answers = [False]
        self.assertIn("Do not retry it", tools.bash("touch a.txt"))

    def test_bash_denied(self):
        self.answers = [False]
        self.assertIn("denied", tools.bash("touch a.txt"))
        self.assertFalse(Path(self.tmp.name, "a.txt").exists())

    def test_bash_timeout(self):
        tools.BASH_TIMEOUT_SECONDS = 1
        try:
            self.assertIn("timed out", tools.bash("sleep 3"))
        finally:
            tools.BASH_TIMEOUT_SECONDS = 30

    def test_overwrite_of_unread_file_is_blocked(self):
        self.make("a.txt", "original")
        self.assertIn("have not read it", tools.write_file("a.txt", "new"))
        self.assertEqual(Path(self.tmp.name, "a.txt").read_text(), "original")

    def test_overwrite_after_reading_is_allowed(self):
        self.make("a.txt", "original")
        tools.read_file("a.txt")
        self.assertIn("Wrote", tools.write_file("a.txt", "new"))
        self.assertEqual(Path(self.tmp.name, "a.txt").read_text(), "new")

    def test_new_file_needs_no_read(self):
        self.assertIn("Wrote", tools.write_file("fresh.txt", "x"))

    def test_file_the_model_wrote_can_be_overwritten(self):
        tools.write_file("fresh.txt", "one")
        self.assertIn("Wrote", tools.write_file("fresh.txt", "two"))

    def test_guard_can_be_turned_off(self):
        tools.REQUIRE_READ_BEFORE_CHANGE = False
        self.make("a.txt", "original")
        self.assertIn("Wrote", tools.write_file("a.txt", "new"))

    def test_changing_the_root_forgets_reads(self):
        self.make("a.txt", "original")
        tools.read_file("a.txt")
        tools.set_root(self.tmp.name)
        self.assertIn("have not read it", tools.write_file("a.txt", "new"))

    def test_failed_read_does_not_count_as_reading(self):
        self.make("b.bin", "x")
        Path(self.tmp.name, "b.bin").write_bytes(b"\xff\xfe\x00")
        tools.read_file("b.bin")
        self.assertIn("have not read it", tools.write_file("b.bin", "new"))

    def test_edit_replaces_one_occurrence(self):
        self.make("a.py", "x = 1\ny = 2\n")
        tools.read_file("a.py")
        self.assertIn("Edited a.py", tools.edit_file("a.py", "x = 1", "x = 5"))
        self.assertEqual(Path(self.tmp.name, "a.py").read_text(), "x = 5\ny = 2\n")

    def test_edit_unread_file_is_blocked(self):
        self.make("a.py", "x = 1\n")
        self.assertIn("have not read it", tools.edit_file("a.py", "x = 1", "x = 5"))

    def test_edit_text_not_found(self):
        self.make("a.py", "x = 1\n")
        tools.read_file("a.py")
        self.assertIn("not found in a.py", tools.edit_file("a.py", "z = 9", "z = 0"))

    def test_edit_text_found_twice(self):
        self.make("a.py", "x = 1\nx = 1\n")
        tools.read_file("a.py")
        out = tools.edit_file("a.py", "x = 1", "x = 2")
        self.assertIn("appears 2 times", out)
        self.assertEqual(Path(self.tmp.name, "a.py").read_text(), "x = 1\nx = 1\n")

    def test_edit_empty_old_text(self):
        self.make("a.py", "x = 1\n")
        tools.read_file("a.py")
        self.assertIn("must not be empty", tools.edit_file("a.py", "", "y"))

    def test_edit_missing_file(self):
        self.assertIn("file not found", tools.edit_file("nope.py", "a", "b"))

    def test_edit_outside_root(self):
        self.assertIn("outside the project folder", tools.edit_file("../x.py", "a", "b"))

    def test_edit_denied(self):
        self.make("a.py", "x = 1\n")
        tools.read_file("a.py")
        self.answers = [False]
        self.assertIn("denied", tools.edit_file("a.py", "x = 1", "x = 5"))
        self.assertEqual(Path(self.tmp.name, "a.py").read_text(), "x = 1\n")

    def test_confirmation_shows_a_preview(self):
        asked = []
        tools.confirm = lambda question: asked.append(question) or True
        tools.write_file("a.txt", "hello world")
        self.assertIn("hello world", asked[0])


class SchemaTests(unittest.TestCase):
    def test_sdk_builds_schemas_with_descriptions(self):
        from ollama._utils import convert_function_to_tool

        for tool in tools.TOOLS:
            schema = convert_function_to_tool(tool).model_dump(exclude_none=True)
            params = schema["function"]["parameters"]["properties"]
            self.assertTrue(params, tool.__name__)
            for name, spec in params.items():
                self.assertTrue(spec.get("description"), f"{tool.__name__}.{name}")


if __name__ == "__main__":
    unittest.main()
