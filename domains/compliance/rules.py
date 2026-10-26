"""Safety rules for the document-review domain.

Fewer rules than the equipment side, but the same principle: the system must not
let a human outsource a signature to it, no matter how the question is phrased.
"""

from __future__ import annotations

from domains.base import SafetyRule

RULES: list[SafetyRule] = [
    SafetyRule(
        "C-SAFE-01",
        r"(代签|帮我签|直接签|代替审核|替我批|帮我批)",
        "文件评审与批准须由授权人员本人签署，代理签署无效",
    ),
    SafetyRule(
        "C-SAFE-02",
        r"(直接发布|直接生效|不用审|跳过审批|绕过审核)",
        "体系文件须经评审批准后发布，不得跳过审批",
    ),
    SafetyRule(
        "C-SAFE-03",
        r"(改|修改|调整|倒).{0,6}(日期|时间)|(日期|时间).{0,6}(改|修改|调整)|补个记录|倒签|补签",
        "记录不得倒签或补签，日期须与实际活动一致",
    ),
]

ENTITY_PATTERNS: dict[str, str] = {
    "clause": r"\d+\.\d+(?:\.\d+)?",
    "standard": r"(GB/T\s?\d{4,5}|ISO\s?\d{4,5})",
}


# Topics this knowledge base deliberately does not cover. A question about them
# must be refused as "not in scope", not answered from a neighbouring clause.
OUT_OF_SCOPE: list[tuple[str, str]] = [
    (r"(环境管理体系|ISO\s?14001|14001)", "环境管理体系（ISO 14001）"),
    (r"(职业健康|ISO\s?45001|45001)", "职业健康安全管理体系"),
    (r"(许可证|资质证书|营业执照|生产许可)", "资质与证照"),
    (r"(卓越绩效|自评得分|评分结果)", "卓越绩效评价"),
    (r"(外审员|审核员|联系电话|联系方式|电话)", "人员与联系方式"),
]
