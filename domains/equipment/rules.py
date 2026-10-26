"""Safety rules for the equipment domain.

Each rule is a regex plus a canned response. A hit short-circuits the request
before any retrieval or model call happens: the point is that the system never
gets a chance to reason its way into a dangerous answer.

Rules are intentionally narrow. A rule that fires on innocent questions lowers
trust faster than a missing rule, so the eval set measures the false-block rate
alongside the hit rate.
"""

from __future__ import annotations

from domains.base import SafetyRule

RULES: list[SafetyRule] = [
    SafetyRule(
        "E-SAFE-01",
        r"(带电|通电|未断电|不断电).{0,8}(拆|接线|检修|开柜|作业)",
        "电气作业须停电、验电、挂牌上锁（LOTO）后由持证电工执行",
    ),
    SafetyRule(
        "E-SAFE-02",
        r"(带压|未泄压|不泄压).{0,8}(拆|更换|紧固|开盖)",
        "承压部件禁止带压拆检，须泄压至表压为零并确认压力表回零",
    ),
    SafetyRule(
        "E-SAFE-03",
        r"(防爆区|0\s*区|1\s*区|2\s*区).{0,10}(动火|焊接|打磨|切割)",
        "爆炸危险区域内动火须办理动火作业票并经气体分析合格",
    ),
    SafetyRule(
        "E-SAFE-04",
        r"(受限空间|入罐|进罐|清罐|下井)",
        "受限空间作业须先通风、气体分析合格并设专人监护",
    ),
    SafetyRule(
        "E-SAFE-05",
        r"(短接|旁通|屏蔽|取掉|拆除).{0,6}(联锁|保护|安全阀|报警|急停)"
        r"|(联锁|保护|安全阀|报警|急停).{0,6}(短接|旁通|屏蔽|取掉|拆除)",
        "安全联锁与保护装置严禁短接或屏蔽，须恢复后方可运行",
    ),
    SafetyRule(
        "E-SAFE-06",
        r"(高温|热态|未降温).{0,8}(拆|打开|紧固|触摸)",
        "高温部件须冷却至 40 ℃ 以下方可作业，作业时佩戴隔热手套",
    ),
    SafetyRule(
        "E-SAFE-07",
        r"(单人|一个人|自己去).{0,6}(检修|作业|处理)",
        "承压与电气检修须两人以上作业，一人作业一人监护",
    ),
    SafetyRule(
        "E-SAFE-08",
        r"(敲击|锤击|撬动).{0,8}(板片|换热器|承压)",
        "板片组与承压部件禁止敲击撬动，重新夹紧须按对角顺序分次施力",
    ),
    SafetyRule(
        "E-SAFE-09",
        r"(补焊|焊接).{0,6}(板片|叶轮|泵壳|承压)",
        "承压部件与板片禁止补焊修复，须整体更换",
    ),
    SafetyRule(
        "E-SAFE-10",
        r"(盘不动|抱死|卡死).{0,8}(强行|硬|直接)(启动|盘车)",
        "主机或泵轴抱死时禁止强行启动，须先解体查明原因",
    ),
    SafetyRule(
        "E-SAFE-11",
        r"(超过|高于).{0,6}(设计压力|额定压力).{0,6}(运行|使用)",
        "超过设计压力运行须立即降载，并报设备科评估",
    ),
    SafetyRule(
        "E-SAFE-12",
        r"(无票|不办票|不申请).{0,8}(动火|高处|吊装|受限空间)",
        "特殊作业须先办理作业票，无票作业一律不得开工",
    ),
    SafetyRule(
        "E-SAFE-13",
        r"(直接|徒手).{0,6}(接触|用手).{0,4}(介质|化学|液体|酸碱)",
        "接触工艺介质须确认 MSDS 并佩戴对应防护用品",
    ),
    SafetyRule(
        "E-SAFE-14",
        r"(拆除|取下).{0,6}(防护罩|防护栏|接地)",
        "防护装置与接地不得在运行期间拆除，检修后须恢复并经确认",
    ),
]

ENTITY_PATTERNS: dict[str, str] = {
    "device_id": r"\b[A-Z]{2}-\d{4}-\d{2}\b",
    "model_id": r"\b(AX\d{3}|BP\d{4}|HE\d{3})\b",
    "part_no": r"\b[A-Z]{2,4}\d{3,4}-[A-Z0-9]{1,4}\b",
}
