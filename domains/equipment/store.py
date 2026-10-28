"""Data access for the equipment domain: manuals, tickets, sensors, registry.

Everything is loaded once and cached in-process. Manuals are parsed from the
generated PDFs (not from the markdown sources) because the PDF path is the one we
claim to handle.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from core.config import DATA_DIR
from core.rag.index import Index
from core.rag.loader import load_pdf
from core.types import Chunk

EQ = DATA_DIR / "equipment"
MAN_DIR = EQ / "manuals"
TICKET_CSV = EQ / "tickets" / "tickets.csv"
SENSOR_DIR = EQ / "sensors"
REGISTRY = EQ / "registry" / "devices.json"

MANUAL_META = {
    "AX300_manual": {"doc_title": "AX300 螺杆空压机 使用与维护手册", "model_id": "AX300"},
    "AX310_manual": {"doc_title": "AX310 螺杆空压机 使用与维护手册", "model_id": "AX310"},
    "BP2200_manual": {"doc_title": "BP2200 离心泵 使用与维护手册", "model_id": "BP2200"},
    "HE800_manual": {"doc_title": "HE800 板式换热器 使用与维护手册", "model_id": "HE800"},
}

# 真实手册通道：厂商公开手册由用户自行下载，放在 manuals/real/ 下，
# 元数据写在 manuals/real/_meta.json。合成清单不动，两者合并使用。
# 这样"换成真手册"只是丢文件 + 写一行 JSON，不用改代码。
REAL_DIR = MAN_DIR / "real"
REAL_META = REAL_DIR / "_meta.json"


def real_meta() -> dict:
    """真实手册的登记表。没有就返回空字典，不是错误状态。"""

    if not REAL_META.is_file():
        return {}
    return json.loads(REAL_META.read_text(encoding="utf-8"))


def manual_meta() -> dict:
    """合成 + 真实，合并后的手册清单。

    每次调用都重读真实登记表：换手册不该要求重启进程才能生效，
    而合成那部分在模块加载时就定了，没必要重复读。
    """

    return {**MANUAL_META, **real_meta()}


def manual_path(doc_id: str) -> Path | None:
    for candidate in (MAN_DIR / f"{doc_id}.pdf", REAL_DIR / f"{doc_id}.pdf"):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def chunks() -> tuple[Chunk, ...]:
    out: list[Chunk] = []
    for doc_id, meta in manual_meta().items():
        pdf = MAN_DIR / f"{doc_id}.pdf"
        if not pdf.is_file():
            pdf = REAL_DIR / f"{doc_id}.pdf"
        if not pdf.is_file():
            continue
        out.extend(
            load_pdf(
                pdf,
                {
                    "doc_id": doc_id,
                    "doc_title": meta["doc_title"],
                    "model_id": meta["model_id"],
                    "doc_type": "manual",
                },
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def index() -> Index:
    return Index(list(chunks()))


@lru_cache(maxsize=1)
def devices() -> dict[str, dict]:
    if not REGISTRY.is_file():
        return {}
    return {d["device_id"]: d for d in json.loads(REGISTRY.read_text(encoding="utf-8"))}


@lru_cache(maxsize=1)
def tickets() -> tuple[dict, ...]:
    if not TICKET_CSV.is_file():
        return ()
    with TICKET_CSV.open(encoding="utf-8") as f:
        return tuple(csv.DictReader(f))


@lru_cache(maxsize=8)
def sensor_series(device_id: str) -> tuple[dict, ...]:
    path = SENSOR_DIR / f"{device_id}.csv"
    if not path.is_file():
        return ()
    with path.open(encoding="utf-8") as f:
        return tuple(csv.DictReader(f))


def latest_reading(device_id: str) -> dict | None:
    """Last sample at or before the pinned demo time."""

    from core.config import settings

    series = sensor_series(device_id)
    if not series:
        return None
    upto = [row for row in series if row["ts"] <= settings.demo_now]
    row = upto[-1] if upto else series[0]
    return dict(row)


def lookup_tickets(fault_code: str, model_id: str | None = None, limit: int = 3) -> list[dict]:
    """Same fault code, same model first, then others of the same family."""

    rows = [t for t in tickets() if t["fault_code"].upper() == fault_code.upper()]
    if model_id:
        same = [t for t in rows if t["model_id"] == model_id]
        rest = [t for t in rows if t["model_id"] != model_id]
        rows = same + rest
    rows.sort(key=lambda t: t["created_at"], reverse=True)
    return rows[:limit]


def resolve_model(query: str, device_id: str | None = None) -> str | None:
    """Find the model from the device registry, else from an explicit model code."""

    if device_id and device_id in devices():
        return devices()[device_id]["model_id"]
    for device in devices().values():
        if device["device_id"] in query or device["name"] in query:
            return device["model_id"]
    for model in manual_meta().values():
        if model["model_id"] in query.upper():
            return model["model_id"]
    return None


TYPE_WORDS = {"AX300": ["空压机", "压缩机"], "AX310": ["空压机", "压缩机"], "BP2200": ["泵"], "HE800": ["换热器"]}


def resolve_models(query: str) -> list[str] | None:
    """If the question names a machine type but no model, restrict to that family.

    "空压机" must not be allowed to retrieve from the heat-exchanger manual. This
    is checked before scoring, for the same reason the model filter is.
    """

    hit = [model for model, words in TYPE_WORDS.items() if any(w in query for w in words)]
    return hit or None


def resolve_device(query: str, device_id: str | None = None) -> str | None:
    """Map a shop-floor phrase like "3 号线空压机" onto a device id.

    Kept deliberately simple and explainable: exact id, exact name, or digit+type.
    A miss here is not fatal - the caller keeps going without live readings.
    """

    if device_id and device_id in devices():
        return device_id
    q = re.sub(r"\s+", "", query)
    for device in devices().values():
        if device["device_id"].replace("-", "") in q.replace("-", ""):
            return device["device_id"]
        name = re.sub(r"\s+", "", device["name"])
        if name and name in q:
            return device["device_id"]
        digit = name[:1]
        words = TYPE_WORDS.get(device["model_id"], [])
        if digit and f"{digit}号" in q and any(w in q for w in words):
            return device["device_id"]
    return None
