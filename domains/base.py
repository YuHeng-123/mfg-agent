"""The Domain protocol: the only surface a domain has to implement.

A domain declares four things:
  - what text exists and how it is chunked,
  - which tools it offers,
  - which phrases must short-circuit as unsafe,
  - which entities count as "we have nothing on this".

Everything else (retrieval fusion, citation checking, tracing, scoring) lives in
core/ and is shared. If a domain ever needs the core to know its name, the
abstraction has failed.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from core.types import Chunk, ToolResult


@dataclass(frozen=True)
class SafetyRule:
    """A deterministic rule. A hit short-circuits the whole request."""

    id: str
    pattern: str
    message: str
    action: str = "转人工"


@dataclass
class Tool:
    """A tool the agent loop is allowed to call.

    `primary` marks the one tool that every request must run (the retrieval step).
    `trigger` is a regex the question must match before the tool is worth calling;
    the loop uses these to build the plan, so tool choice stays declarative and
    identical in stub and real mode.
    """

    name: str
    description: str
    fn: Callable[..., ToolResult]
    read_only: bool = True
    parallel_safe: bool = True
    primary: bool = False
    trigger: str | None = None

    def __call__(self, **kwargs: Any) -> ToolResult:
        return self.fn(**kwargs)


@dataclass(frozen=True)
class EvalItem:
    """One labelled evaluation sample."""

    id: str
    domain: str
    question: str
    kind: str  # fault_code | procedure | parameter | gap_exists | missing_doc | refuse
    gold_chunk_ids: tuple[str, ...] = ()
    gold_gap_ids: tuple[str, ...] = ()
    refuse_kind: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Domain(Protocol):
    name: str
    label: str

    def load_chunks(self) -> list[Chunk]: ...

    def index(self) -> Any:
        """The domain's own index. Built on demand, warmed at startup."""

    def sources(self) -> list[Path]:
        """Files the startup self-check looks for."""

    def tools(self) -> dict[str, Tool]: ...

    def safety_rules(self) -> list[SafetyRule]: ...

    def entity_patterns(self) -> dict[str, str]: ...

    def eval_items(self) -> list[EvalItem]: ...

    def prompt_profile(self) -> dict[str, str]: ...


_REGISTRY: dict[str, str] = {
    "equipment": "domains.equipment.domain:EquipmentDomain",
    "compliance": "domains.compliance.domain:ComplianceDomain",
}

_CACHE: dict[str, Domain] = {}


def available() -> list[str]:
    return list(_REGISTRY)


def load_domain(name: str) -> Domain:
    """Import and cache a domain by name."""

    if name in _CACHE:
        return _CACHE[name]
    if name not in _REGISTRY:
        raise KeyError(f"unknown domain: {name}; available={available()}")
    module_path, _, class_name = _REGISTRY[name].partition(":")
    module = importlib.import_module(module_path)
    instance = getattr(module, class_name)()
    _CACHE[name] = instance
    return instance
