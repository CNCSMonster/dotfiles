"""Module dependency and tool conflict resolution."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .errors import DependencyError
from .models import ModuleSpec, ToolSpec, ToolsConfig


def resolve_modules(config: ToolsConfig, target_module: str) -> List[ModuleSpec]:
    order: List[ModuleSpec] = []
    visited: Set[str] = set()
    visiting: List[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join(visiting + [name])
            raise DependencyError(f"Dependency cycle detected: {cycle}")
        module = config.modules.get(name)
        if module is None:
            raise DependencyError(f"Missing dependency module: {name}")
        visiting.append(name)
        for dependency in module.depends:
            visit(dependency)
        visiting.pop()
        visited.add(name)
        order.append(module)

    visit(target_module)
    return order


def collect_ordered_tools(modules: List[ModuleSpec]) -> List[Tuple[str, ToolSpec]]:
    seen: Dict[str, str] = {}
    ordered: List[Tuple[str, ToolSpec]] = []
    for module in modules:
        for tool in module.tools:
            name = tool.reference.name
            if name in seen:
                raise DependencyError(f"Duplicate tool name {name!r} in selected scope: {seen[name]} and {module.name}")
            seen[name] = module.name
            ordered.append((module.name, tool))
    return ordered
