"""Metric definitions. Pure functions so they can be unit-tested without data."""

from __future__ import annotations


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 0.0
    top = set(retrieved[:k])
    return len(top & set(gold)) / len(gold)


def hit_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """1.0 if any gold paragraph is in the top k.

    Different from recall_at_k on purpose: when a question has two acceptable
    answers, hitting one of them is a success, but set-recall would score 0.5.
    The equipment set has such questions, so both numbers get reported.
    """

    if not gold:
        return 0.0
    return 1.0 if set(retrieved[:k]) & set(gold) else 0.0


def reciprocal_rank(retrieved: list[str], gold: list[str]) -> float:
    gold_set = set(gold)
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in gold_set:
            return 1.0 / rank
    return 0.0


def citation_precision(cited: list[str], gold: list[str]) -> float:
    """Share of what we cited that the labels agree with."""

    if not cited:
        return 0.0
    return len(set(cited) & set(gold)) / len(set(cited))


def citation_recall(cited: list[str], gold: list[str]) -> float:
    """Did at least one gold chunk get cited. Answer-level hit rate."""

    if not gold:
        return 0.0
    return 1.0 if set(cited) & set(gold) else 0.0


def confusion(should_answer: list[bool], did_answer: list[bool]) -> dict[str, int]:
    """2x2 over (should answer?) x (did answer?)."""

    cells = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for should, did in zip(should_answer, did_answer):
        if should and did:
            cells["tp"] += 1
        elif should and not did:
            cells["fn"] += 1
        elif not should and did:
            cells["fp"] += 1
        else:
            cells["tn"] += 1
    return cells


def rates(cells: dict[str, int]) -> dict[str, float]:
    answered = cells["tp"] + cells["fp"]
    refused = cells["fn"] + cells["tn"]
    expected_answer = cells["tp"] + cells["fn"]
    expected_refuse = cells["fp"] + cells["tn"]
    return {
        "refusal_correct": cells["tn"] / expected_refuse if expected_refuse else 0.0,
        "over_refusal": cells["fn"] / expected_answer if expected_answer else 0.0,
        "answered": answered,
        "refused": refused,
    }
