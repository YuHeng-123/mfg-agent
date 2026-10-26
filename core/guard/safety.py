"""Safety gate: deterministic short circuit.

Nothing here talks to a model. The rules are regexes written by a human, the hit
is decided before retrieval, and the response is a fixed sentence. If we let a
model decide whether "带电拆开接线盒" is safe, we have already lost the argument.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.types import Refusal
from domains.base import SafetyRule


@dataclass(frozen=True)
class SafetyHit:
    rule_id: str
    pattern: str
    message: str
    action: str

    def to_refusal(self) -> Refusal:
        return Refusal(
            kind="safety_blocked",
            reason=f"命中安全规则 {self.rule_id}：{self.message}",
            missing=[],
            action=self.action,
        )


def check(question: str, rules: list[SafetyRule]) -> SafetyHit | None:
    for rule in rules:
        if re.search(rule.pattern, question):
            return SafetyHit(rule.id, rule.pattern, rule.message, rule.action)
    return None
