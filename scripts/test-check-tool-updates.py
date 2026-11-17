#!/usr/bin/env python3
"""Offline regression tests: compile only selected embedded function AST nodes."""
import ast
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def load_functions():
    script = Path(__file__).with_name("check-tool-updates.sh").read_text()
    source = script.split("<<'PYEOF'\n", 1)[1].rsplit("\nPYEOF", 1)[0]
    names = {"gh_repo_latest", "crate_latest", "npm_latest", "pypi_latest", "norm"}
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise AssertionError("missing embedded functions")
    # No imports, configuration loads, dispatch loop or network startup is executed.
    namespace = {"subprocess": SimpleNamespace(
        run=Mock(), TimeoutExpired=subprocess.TimeoutExpired),
        "http_json": Mock(side_effect=AssertionError("unexpected HTTP request")),
        "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<embedded functions>", "exec"), namespace)
    return namespace


class UpdateCheckerTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_functions()
        self.run = self.ns["subprocess"].run
        self.http = self.ns["http_json"]

    def github(self):
        result = self.ns["gh_repo_latest"]("owner/project")
        self.http.assert_not_called()
        self.run.assert_called_once_with(
            ["gh", "api", "repos/owner/project/releases/latest", "--jq", ".tag_name"],
            capture_output=True, text=True, timeout=60)
        return result

    def test_success_tag(self):
        self.run.return_value = SimpleNamespace(returncode=0, stdout=" v1.2.3\n")
        self.assertEqual(self.github(), "v1.2.3")

    def test_nonzero_retains_exit_attribution_without_output(self):
        for code in (1, 4, 127):
            with self.subTest(code=code):
                self.run.reset_mock()
                self.run.return_value = SimpleNamespace(
                    returncode=code, stdout="SECRET-STDOUT", stderr="SECRET-STDERR")
                self.assertEqual(self.github(), f"err:gh api failed (exit {code}); check gh authentication/access")

    def test_timeout_does_not_leak_exception_output(self):
        self.run.side_effect = subprocess.TimeoutExpired(
            ["gh", "SECRET-COMMAND"], 60, output="SECRET", stderr="SECRET")
        self.assertEqual(self.github(), "err:gh api timed out after 60s")

    def test_missing_gh(self):
        self.run.side_effect = FileNotFoundError("SECRET")
        self.assertEqual(self.github(), "err:gh executable not found")

    def test_os_error(self):
        self.run.side_effect = PermissionError(13, "SECRET")
        self.assertEqual(self.github(), "err:gh api could not start (errno 13)")

    def test_empty_stdout(self):
        for output in ("", " \n\t"):
            with self.subTest(output=output):
                self.run.reset_mock()
                self.run.return_value = SimpleNamespace(returncode=0, stdout=output)
                self.assertEqual(self.github(), "err:gh api returned empty tag_name")

    def test_other_registries_unchanged(self):
        cases = [
            ("crate_latest", "demo", "https://crates.io/api/v1/crates/demo", {"crate": {"max_version": "2.0"}}),
            ("npm_latest", "@scope/demo", "https://registry.npmjs.org/@scope/demo/latest", {"version": "2.0"}),
            ("pypi_latest", "demo", "https://pypi.org/pypi/demo/json", {"info": {"version": "2.0"}}),
        ]
        for function, name, url, payload in cases:
            with self.subTest(function=function):
                self.http.reset_mock()
                self.http.side_effect = None
                self.http.return_value = payload
                self.assertEqual(self.ns[function](name), "2.0")
                self.http.assert_called_once_with(url)
                self.http.side_effect = ValueError("registry failure")
                self.assertEqual(self.ns[function](name), "err:registry failure")
        self.run.assert_not_called()

    def test_normalization_unchanged(self):
        self.assertEqual(self.ns["norm"](' "V1.2.3" '), "1.2.3")
        self.assertEqual(self.ns["norm"](None), "?")


if __name__ == "__main__":
    unittest.main()
