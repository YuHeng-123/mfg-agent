"""Generate the synthetic operational data: tickets and sensor series.

Everything here is fabricated and says so in the README. The shape matters more
than the volume: fault codes must line up with the manuals, ticket actions must
look like what a maintenance crew actually writes, and the sensor series must
contain the anomaly windows the demo relies on.

Run:  python scripts/gen_data.py
Out:  data/equipment/tickets/tickets.csv
      data/equipment/sensors/*.csv
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "equipment"
SEED = 20261026

FAULTS: dict[str, dict[str, tuple[str, list[str], int]]] = {
    "AX300": {
        "E01": ("排气压力过高", ["调整压力上限并复紧进气阀气缸", "更换压力变送器", "清洗进气阀阀板"], 3),
        "E02": ("排气压力过低", ["检查管路泄漏点并更换密封垫", "更换进气阀密封圈", "复紧法兰螺栓"], 2),
        "E05": ("排气温度过高", ["清洗冷却器并更换空气滤芯", "恢复冷却水流量后复测进出水温差", "补充润滑油并更换油滤"], 4),
        "E06": ("油温过高", ["清洗油冷却器", "更换温控阀芯", "更换润滑油"], 4),
        "E07": ("油压过低", ["更换油滤", "更换油泵", "检查单向阀密封面"], 5),
        "E08": ("主机振动超标", ["重新对中并复紧地脚螺栓", "更换联轴器弹性体", "拆检主机轴承"], 8),
        "E09": ("电流过载", ["更换接触器", "报电气班测量三相电压", "盘车确认主机转动灵活"], 4),
        "E05x": ("排气温度过高", ["化学清洗冷却器", "加装强制通风", "下调负载至 70%"], 6),
    },
    "AX310": {
        "E05": ("排气温度过高", ["清洗冷却器并更换 AX310-F 滤芯", "恢复冷却水流量后复测进出水温差"], 4),
        "E06": ("油温过高", ["清洗油冷却器", "更换润滑油"], 4),
        "E08": ("主机振动超标", ["按 180 N·m 复紧地脚螺栓", "更换联轴器弹性体"], 7),
        "E09": ("电流过载", ["更换接触器", "报电气班测量三相电压"], 4),
    },
    "BP2200": {
        "P01": ("出口压力不足", ["更换口环", "清理叶轮堵塞", "检查止回阀"], 4),
        "P02": ("流量不足", ["清洗入口滤网", "检查出口阀开度", "复测转速"], 3),
        "P03": ("电机过载", ["重新对中", "更换轴承", "核对介质密度"], 5),
        "P04": ("汽蚀", ["提高吸入罐液位", "清洗入口滤网", "降低介质温度"], 3),
        "P05": ("机械密封泄漏", ["更换集装式机械密封", "疏通密封冲洗管线", "更换限流孔板"], 5),
        "P06": ("轴承温度高", ["补充润滑脂至腔体三分之一", "恢复轴承冷却水", "更换轴承"], 4),
        "P07": ("振动超标", ["复紧地脚螺栓", "叶轮做动平衡", "复测对中"], 6),
        "P09": ("联轴器打滑", ["更换弹性块", "修复键槽"], 5),
    },
    "HE800": {
        "H01": ("换热效率下降", ["拆解清洗板片", "更换垫片", "补充缺失板片"], 8),
        "H02": ("压降升高", ["清洗板片结垢", "清洗入口过滤器", "复核板片装向"], 7),
        "H03": ("外漏", ["按对角顺序补紧至铭牌尺寸", "整体更换垫片", "复紧夹紧螺栓"], 5),
        "H04": ("内漏", ["更换穿孔板片", "整体更换垫片"], 9),
        "H05": ("板片腐蚀穿孔", ["更换板片", "取样分析氯离子浓度", "停机排空冲洗"], 10),
    },
}

DEVICES = {
    "AX300": ["AC-300-01", "AC-300-02", "AC-300-03"],
    "AX310": ["AC-310-01"],
    "BP2200": ["PU-2200-01", "PU-2200-02"],
    "HE800": ["HX-800-01"],
}

LINES = {
    "AX300": "3 号线动力站",
    "AX310": "4 号线动力站",
    "BP2200": "2 号线输送单元",
    "HE800": "1 号线换热单元",
}

ACTORS = ["张伟", "李强", "王建国", "陈磊", "刘洋", "赵鹏"]


def gen_tickets(n: int = 300) -> list[dict]:
    rng = random.Random(SEED)
    rows: list[dict] = []
    start = datetime(2025, 10, 1, 8, 0)
    weights = {"AX300": 0.40, "AX310": 0.12, "BP2200": 0.31, "HE800": 0.17}

    for i in range(n):
        model = rng.choices(list(weights), weights=list(weights.values()))[0]
        code = rng.choice([c for c in FAULTS[model] if not c.endswith("x")])
        name, actions, base_hours = FAULTS[model][code]
        device = rng.choice(DEVICES[model])

        result = rng.choices(["已解决", "升级处理", "返厂维修"], weights=[0.68, 0.22, 0.10])[0]
        hours = round(base_hours * rng.uniform(0.6, 1.8) + (2.5 if result != "已解决" else 0), 1)
        created = start + timedelta(hours=rng.randint(0, 24 * 280))

        rows.append(
            {
                "ticket_id": f"T{created:%Y%m%d}-{i:03d}",
                "created_at": created.strftime("%Y-%m-%d %H:%M"),
                "model_id": model,
                "device_id": device,
                "line": LINES[model],
                "fault_code": code,
                "symptom": f"{name}，班组巡检发现并报修" if rng.random() < 0.6 else f"{name}，中控报警触发",
                "action": rng.choice(actions),
                "hours": hours,
                "result": result,
                "owner": rng.choice(ACTORS),
            }
        )
    rows.sort(key=lambda r: r["created_at"])
    return rows


def gen_sensors() -> None:
    rng = random.Random(SEED + 1)
    out = DATA / "sensors"
    out.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 10, 19, 0, 0)
    minutes = 7 * 24 * 60

    baselines = {
        "AC-300-01": (78.0, 2.0, 88.0),
        "AC-300-02": (80.0, 2.1, 90.0),
        "AC-300-03": (86.0, 2.6, 96.0),
        "PU-2200-01": (52.0, 2.3, 71.0),
        "PU-2200-02": (54.0, 2.4, 72.0),
        "HX-800-01": (61.0, 1.6, 34.0),
    }
    # Anomalies are planted on purpose: the demo question about 3 号空压机 has to
    # find a real excursion, not a number we typed into the answer.
    anomalies = {
        "AC-300-03": [(5 * 1440 + 600, 5 * 1440 + 780, 34.0, 2.6, 6.0)],
        "PU-2200-01": [(3 * 1440 + 300, 3 * 1440 + 420, 9.0, 2.2, 8.0)],
        "HX-800-01": [(6 * 1440 + 120, 6 * 1440 + 260, 12.0, 0.4, 3.0)],
    }

    for device, (t0, v0, a0) in baselines.items():
        path = out / f"{device}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "device_id", "temp_c", "vibration_mm_s", "current_a"])
            for m in range(minutes):
                ts = start + timedelta(minutes=m)
                temp = t0 + 3.0 * rng.random() + 4.0 * __import__("math").sin(m / 200)
                vib = v0 + 0.25 * rng.random()
                cur = a0 + 1.5 * rng.random()
                for (s, e, dt, dv, da) in anomalies.get(device, []):
                    if s <= m <= e:
                        prog = (m - s) / max(e - s, 1)
                        temp += dt * prog
                        vib += dv * prog
                        cur += da * prog
                w.writerow([ts.strftime("%Y-%m-%d %H:%M"), device, f"{temp:.1f}", f"{vib:.2f}", f"{cur:.1f}"])
        print(f"sensors  {device:12s} rows={minutes}")


def main() -> None:
    tk = DATA / "tickets"
    tk.mkdir(parents=True, exist_ok=True)
    rows = gen_tickets()
    path = tk / "tickets.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"tickets  {path.name} rows={len(rows)}")
    gen_sensors()

    # small index so a reader can see what the codes mean without opening a PDF
    (DATA / "registry" / "faults.json").write_text(
        json.dumps(
            {m: {c: {"name": v[0], "typical_hours": v[2]} for c, v in codes.items()} for m, codes in FAULTS.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
