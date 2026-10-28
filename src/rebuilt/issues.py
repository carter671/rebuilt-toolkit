from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Issue:
    code: str  # stable, machine-readable, e.g. "REF_MISSING_HOST"
    severity: Severity
    message: str
    elements: tuple[str, ...] = ()
    path: str = ""
    layer: str = ""  # schema | reference | units | architecture | profile | compile | export

    def to_dict(self) -> dict:
        d = asdict(self)
        d["elements"] = list(self.elements)
        return d


@dataclass
class IssueList:
    items: list[Issue] = field(default_factory=list)

    def add(self, code, severity, message, elements=(), path="", layer=""):
        self.items.append(Issue(code, severity, message, tuple(elements), path, layer))

    @property
    def errors(self):
        return [i for i in self.items if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.items if i.severity == "warning"]

    def codes(self) -> set[str]:
        return {i.code for i in self.items}

    def extend(self, other: "IssueList"):
        self.items.extend(other.items)

    def sorted(self):
        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(self.items, key=lambda i: (order[i.severity], i.code, i.elements, i.path))
