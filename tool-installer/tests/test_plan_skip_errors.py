"""build_install_plan 的 skip_errors 语义测试。

CI 用一轮枚举把 tools.toml 里每个模块都 dry-run 一遍。若单个条目的策略写坏了就
抛异常中止，那么该条目之后的工具、乃至之后的模块都得不到解析——覆盖面静默缩水。
skip_errors 只豁免"这一个条目解析不出来"，跨条目的结构约束仍必须硬失败。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.errors import ManifestError, StrategyError  # noqa: E402
from tool_installer.models import Environment, ToolReference, ToolSpec  # noqa: E402
from tool_installer.strategy import build_install_plan  # noqa: E402

LINUX = Environment(os="linux", arch="x86_64")


def tool(name: str, version: str = "1.0.0") -> tuple[str, ToolSpec]:
    return ("mod", ToolSpec(reference=ToolReference(raw=f"{name}@{version}", name=name, version=version)))


GOOD = {"manager": "cargo-install", "pkg": "good", "linux": {"manager": "cargo-install", "pkg": "good"}}
BROKEN = {"manager": "cargo-install", "pkg": "broken", "linux": {"manager": "no-such-manager"}}
DUPLICATE_DEFAULT = {
    "manager": "rustup",
    "linux": {"manager": "rustup", "set_default": True},
}


class SkipErrors(unittest.TestCase):
    def test_bad_entry_aborts_plan_by_default(self):
        with self.assertRaises(StrategyError):
            build_install_plan([tool("good"), tool("broken")], {"good": GOOD, "broken": BROKEN}, LINUX, Path("."))

    def test_bad_entry_is_tolerated_and_later_tools_still_planned(self):
        plan = build_install_plan(
            [tool("broken"), tool("good")],
            {"good": GOOD, "broken": BROKEN},
            LINUX,
            Path("."),
            skip_errors=True,
        )
        self.assertEqual([i.tool.reference.name for i in plan.items], ["good"])

    def test_missing_manifest_entry_is_tolerated(self):
        plan = build_install_plan([tool("ghost")], {}, LINUX, Path("."), skip_errors=True)
        self.assertEqual(plan.items, [])
        with self.assertRaises(ManifestError):
            build_install_plan([tool("ghost")], {}, LINUX, Path("."))

    def test_structural_invariant_still_fails_with_skip_errors(self):
        # 两个 rustup 都 set_default：这是跨条目约束，不是单条目解析失败。
        with self.assertRaises(StrategyError):
            build_install_plan(
                [tool("rust-a"), tool("rust-b")],
                {"rust-a": DUPLICATE_DEFAULT, "rust-b": DUPLICATE_DEFAULT},
                LINUX,
                Path("."),
                skip_errors=True,
            )

    def test_clean_plan_identical_with_and_without_skip_errors(self):
        tools = [tool("good")]
        strict = build_install_plan(tools, {"good": GOOD}, LINUX, Path("."))
        lenient = build_install_plan(tools, {"good": GOOD}, LINUX, Path("."), skip_errors=True)
        self.assertEqual(
            [i.tool.reference.name for i in strict.items],
            [i.tool.reference.name for i in lenient.items],
        )


if __name__ == "__main__":
    unittest.main()
