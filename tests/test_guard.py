from __future__ import annotations

from core.guard import citation as citation_guard
from core.guard import evidence as evidence_guard
from core.guard import safety as safety_guard
from core.types import Citation, Claim, EvidenceStats, ToolResult
from domains.equipment.rules import RULES


def test_safety_blocks_live_electrical_work():
    hit = safety_guard.check("带电拆开接线盒检查", RULES)
    assert hit is not None
    assert hit.rule_id == "E-SAFE-01"
    refusal = hit.to_refusal()
    assert refusal.kind == "safety_blocked"
    assert "LOTO" in refusal.reason


def test_safety_blocks_pressure_work():
    assert safety_guard.check("带压拆开冷却器端盖", RULES) is not None


def test_safety_blocks_disabling_interlock():
    hit = safety_guard.check("先把温度联锁屏蔽掉再运行", RULES)
    assert hit is not None
    assert hit.rule_id == "E-SAFE-05"


def test_safety_does_not_fire_on_normal_question():
    for q in [
        "3 号线空压机报 E05，排气温度 118℃，怎么处理？",
        "这台泵的轴承型号是多少？",
        "空压机排气温度报警值是多少",
    ]:
        assert safety_guard.check(q, RULES) is None, q


def test_evidence_refuses_when_no_result():
    refusal = evidence_guard.gate(None, "随便问问")
    assert refusal is not None
    assert refusal.kind == "insufficient_evidence"


def test_evidence_refuses_unknown_model():
    stats = EvidenceStats(matched_terms=5, matched_mass=9.0, hit_count=4, unknowns=("AX900",))
    refusal = evidence_guard.gate(stats, "AX900 报 E05 怎么办")
    assert refusal is not None
    assert any("AX900" in m for m in refusal.missing)


def test_evidence_refuses_thin_match():
    stats = EvidenceStats(matched_terms=1, matched_mass=1.4, hit_count=3)
    refusal = evidence_guard.gate(stats, "这台泵的轴承型号是多少")
    assert refusal is not None
    assert "覆盖不足" in refusal.reason


def test_evidence_passes_on_real_match():
    stats = EvidenceStats(matched_terms=4, matched_mass=6.0, hit_count=4)
    assert evidence_guard.gate(stats, "E05 排气温度高") is None


def _outputs() -> list[tuple[str, ToolResult]]:
    return [
        (
            "search_manual",
            ToolResult(
                ok=True,
                citations=[
                    Citation(chunk_id="M#p1#s01#c01", doc_title="手册", page=1, section="5.3", kind="manual")
                ],
            ),
        )
    ]


def test_citation_rejects_invented_id():
    claims = [Claim(text="拧到 210 N·m", citation_ids=["M#p99#s99#c01"])]
    kept, rejected, refusal = citation_guard.verify(claims, _outputs())
    assert rejected and kept[0].confidence == "low"
    assert refusal is not None and refusal.kind == "insufficient_evidence"


def test_citation_keeps_supported_claim():
    claims = [Claim(text="立即降载至 70%", citation_ids=["M#p1#s01#c01"])]
    kept, rejected, refusal = citation_guard.verify(claims, _outputs())
    assert not rejected and refusal is None and kept[0].confidence == "high"


def test_citation_rejects_claim_without_any_citation():
    claims = [Claim(text="建议每 500 小时换油", citation_ids=[])]
    kept, rejected, refusal = citation_guard.verify(claims, _outputs())
    assert rejected and not kept[0].citation_ids and refusal is not None
