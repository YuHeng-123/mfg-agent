"""Equipment domain: the "retrieve" half of the product."""

from __future__ import annotations

import json

from core.config import ROOT
from core.types import Chunk
from domains.base import Domain, EvalItem, SafetyRule, Tool
from domains.equipment import store
from domains.equipment.rules import ENTITY_PATTERNS, RULES
from domains.equipment.tools import TOOLS

EVAL_PATH = ROOT / "evals" / "equipment.jsonl"


class EquipmentDomain(Domain):
    name = "equipment"
    label = "设备运维"

    def load_chunks(self) -> list[Chunk]:
        return list(store.chunks())

    def tools(self) -> dict[str, Tool]:
        return {
            name: Tool(
                name=name,
                description=spec["description"],
                fn=spec["fn"],
                read_only=spec["read_only"],
                parallel_safe=spec["parallel_safe"],
                primary=spec.get("primary", False),
                trigger=spec.get("trigger"),
            )
            for name, spec in TOOLS.items()
        }

    def safety_rules(self) -> list[SafetyRule]:
        return RULES

    def entity_patterns(self) -> dict[str, str]:
        return ENTITY_PATTERNS

    def eval_items(self) -> list[EvalItem]:
        if not EVAL_PATH.is_file():
            return []
        items = []
        for line in EVAL_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            items.append(
                EvalItem(
                    id=raw["id"],
                    domain=raw.get("domain", self.name),
                    question=raw["q"],
                    kind=raw.get("type", "fault_code"),
                    gold_chunk_ids=tuple(raw.get("gold_chunk_ids", [])),
                    refuse_kind=raw.get("refuse_kind"),
                    context=raw.get("context", {}),
                )
            )
        return items

    def prompt_profile(self) -> dict[str, str]:
        return {
            "role": "工业设备维修助手",
            "answer_shape": "编号处置步骤，每条最多一句话",
            "cite_style": "手册 页码/章节 或 工单号",
        }
