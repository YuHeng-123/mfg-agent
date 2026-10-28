"""进程内指标。没有 Prometheus 客户端依赖，也没有外部时序库。

为什么自己写 40 行而不是引入 prometheus_client：
  - 这个服务是单进程、单容器，指标丢了重启就是了，不需要聚合与持久化；
  - 少一个依赖，镜像小一圈，试点部署时少一个"它为什么起不来"的可能。

暴露的东西（Prometheus 文本格式 + 一个给页面用的 JSON）：
  QPS（60 秒滑窗）、P50/P95/P99 延迟、错误率、拒答率、按域拆分。

这些数字是**本进程自启动以来**的，跨重启归零。要长期的去看审计表，不是看这里。
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque

_LOCK = threading.Lock()
_STARTED = time.time()

_ASK_TOTAL: Counter[tuple[str, str]] = Counter()  # (domain, outcome)
_HTTP_TOTAL: Counter[tuple[str, int]] = Counter()  # (path, status)
_LATENCY: deque[tuple[float, float]] = deque(maxlen=5000)  # (ts, ms)
_ERRORS = 0
_REQUESTS = 0
_WINDOW_S = 60.0


def reset() -> None:
    """测试用：把计数器清干净，别让用例之间互相污染。"""

    global _ERRORS, _REQUESTS, _STARTED
    with _LOCK:
        _ASK_TOTAL.clear()
        _HTTP_TOTAL.clear()
        _LATENCY.clear()
        _ERRORS = 0
        _REQUESTS = 0
        _STARTED = time.time()


def record_http(path: str, status: int, elapsed_ms: float) -> None:
    global _ERRORS, _REQUESTS
    with _LOCK:
        _HTTP_TOTAL[(path, status)] += 1
        _REQUESTS += 1
        if status >= 500:
            _ERRORS += 1
        _LATENCY.append((time.time(), elapsed_ms))


def record_ask(domain: str, outcome: str) -> None:
    """outcome: answered | refused | error"""

    with _LOCK:
        _ASK_TOTAL[(domain, outcome)] += 1


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return ordered[idx]


def snapshot() -> dict:
    now = time.time()
    with _LOCK:
        recent = [ms for ts, ms in _LATENCY if now - ts <= _WINDOW_S]
        all_lat = [ms for _, ms in _LATENCY]
        asked = sum(_ASK_TOTAL.values())
        answered = sum(v for (d, o), v in _ASK_TOTAL.items() if o == "answered")
        refused = sum(v for (d, o), v in _ASK_TOTAL.items() if o == "refused")
        errors = sum(v for (d, o), v in _ASK_TOTAL.items() if o == "error")
        by_domain = {
            d: {o: v for (dd, o), v in _ASK_TOTAL.items() if dd == d}
            for d in {d for d, _ in _ASK_TOTAL}
        }
        window_requests = len(recent)
        return {
            "uptime_s": round(now - _STARTED, 1),
            "qps_60s": round(window_requests / _WINDOW_S, 4),
            "requests_total": _REQUESTS,
            "error_rate": round(_ERRORS / _REQUESTS, 4) if _REQUESTS else 0.0,
            "latency_ms": {
                "p50": round(_percentile(all_lat, 0.50), 1),
                "p95": round(_percentile(all_lat, 0.95), 1),
                "p99": round(_percentile(all_lat, 0.99), 1),
                "samples": len(all_lat),
            },
            "ask_total": asked,
            "refusal_rate": round(refused / asked, 4) if asked else 0.0,
            "error_ask": errors,
            "answered": answered,
            "refused": refused,
            "by_domain": by_domain,
        }


def render_prometheus() -> str:
    s = snapshot()
    lines = [
        "# HELP mfg_uptime_seconds 进程运行时长",
        "# TYPE mfg_uptime_seconds gauge",
        f"mfg_uptime_seconds {s['uptime_s']}",
        "# HELP mfg_qps_60s 最近 60 秒的请求速率",
        "# TYPE mfg_qps_60s gauge",
        f"mfg_qps_60s {s['qps_60s']}",
        "# HELP mfg_http_requests_total HTTP 请求数",
        "# TYPE mfg_http_requests_total counter",
    ]
    with _LOCK:
        http_rows = sorted(_HTTP_TOTAL.items())
        ask_rows = sorted(_ASK_TOTAL.items())
    for (path, status), value in http_rows:
        lines.append(f'mfg_http_requests_total{{path="{path}",status="{status}"}} {value}')

    lines += [
        "# HELP mfg_ask_total 提问数，按域与结果拆分",
        "# TYPE mfg_ask_total counter",
    ]
    for (domain, outcome), value in ask_rows:
        lines.append(f'mfg_ask_total{{domain="{domain}",outcome="{outcome}"}} {value}')

    lines += [
        "# HELP mfg_ask_latency_ms 提问延迟（毫秒）",
        "# TYPE mfg_ask_latency_ms gauge",
        f'mfg_ask_latency_ms{{quantile="0.5"}} {s["latency_ms"]["p50"]}',
        f'mfg_ask_latency_ms{{quantile="0.95"}} {s["latency_ms"]["p95"]}',
        f'mfg_ask_latency_ms{{quantile="0.99"}} {s["latency_ms"]["p99"]}',
        "# HELP mfg_error_rate 5xx 比例",
        "# TYPE mfg_error_rate gauge",
        f"mfg_error_rate {s['error_rate']}",
        "# HELP mfg_refusal_rate 拒答比例",
        "# TYPE mfg_refusal_rate gauge",
        f"mfg_refusal_rate {s['refusal_rate']}",
    ]
    return "\n".join(lines) + "\n"
