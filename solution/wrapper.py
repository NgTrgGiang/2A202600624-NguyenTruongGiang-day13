"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}
"""
from __future__ import annotations

import os
import re
import time
import unicodedata

# ---- Day 13 telemetry toolkit (optional: wrapper still runs without it) -------------
try:
    from telemetry.logger import logger, new_correlation_id, set_correlation_id
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except Exception:  # pragma: no cover
    logger = None

    def new_correlation_id():
        return None

    def set_correlation_id(_cid):
        return None

    def cost_from_usage(_model, _usage):
        return 0.0

    def redact(s):
        return (s, 0)


# ---- Prompt routing: load our rewritten system prompt once -------------------------
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.txt")
try:
    with open(_PROMPT_PATH, encoding="utf-8") as _f:
        _SYSTEM_PROMPT = _f.read().strip()
except Exception:
    _SYSTEM_PROMPT = ""


# ---- Input sanitization: neutralize instructions injected in order notes -----------
# Conservative: only strip trailing snippets that try to SET a price/total or override
# instructions. Normal order text (product / qty / coupon / destination) is preserved.
_INJECT_PAT = re.compile(
    r"(?is)\b(?:b[oỏ]\s*qua|ignore|disregard|override|system\s*:|"
    r"gi[aá]\s*(?:la|là|=|:)\s*\d|t[oổ]ng\s*(?:la|là|=|:)\s*\d|"
    r"set\s+(?:price|total)|mien\s*phi\s*ship|free\s*ship)\b.*$"
)


def _fold_diacritics(s: str) -> str:
    # Strip Vietnamese diacritics so a tool that fails on accented city names
    # (e.g. "đà lạt", "Hà Nội") resolves correctly. Defends the documented
    # diacritic tool_failure even if config.normalize_unicode is unreliable.
    s = s.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _sanitize(question: str) -> str:
    if not isinstance(question, str):
        return question
    question = _fold_diacritics(question)
    parts = re.split(r"[\n;]", question)
    kept = [p for p in parts if not _INJECT_PAT.search(p or "")]
    cleaned = "; ".join(s.strip() for s in kept if s.strip())
    return cleaned or question


def _bad(result) -> bool:
    return (not isinstance(result, dict)) or result.get("status") != "ok"


# ---- Arithmetic guardrail: recompute the exact total from the live tool outputs --
# Legal "arithmetic/guardrail validation": we do NOT look answers up in a table; we
# read the prices/discount/shipping the tools actually returned in result["trace"]
# and recompute total = unit_price*qty*(100-pct)//100 + shipping. This fixes the
# real LLM's frequent multi-digit arithmetic slips on otherwise-valid orders.
def _parse_trace(trace):
    info = {"found": None, "in_stock": None, "stock_qty": None, "unit_price": None,
            "unit_weight": None, "pct": 0, "shipping": None, "ship_weight": None}
    if not isinstance(trace, list):
        return info
    for step in trace:
        if not isinstance(step, dict):
            continue
        obs = step.get("observation")
        if not isinstance(obs, dict):
            continue
        tool = step.get("tool")
        if tool == "check_stock":
            info["found"] = obs.get("found")
            info["in_stock"] = obs.get("in_stock")
            info["stock_qty"] = obs.get("quantity")
            info["unit_price"] = obs.get("unit_price_vnd")
            info["unit_weight"] = obs.get("weight_kg")
        elif tool == "get_discount":
            info["pct"] = obs.get("percent", 0) if obs.get("valid") else 0
        elif tool == "calc_shipping":
            info["shipping"] = obs.get("cost_vnd")
            info["ship_weight"] = obs.get("weight_kg")
    return info


def _order_qty(info, question):
    uw, sw = info.get("unit_weight"), info.get("ship_weight")
    if uw and sw:  # most reliable: shipping weight / unit weight
        q = int(round(sw / uw))
        if q > 0:
            return q
    m = re.search(r"(?:mua|buy)\s+(\d{1,3})", question or "", re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,3})\b", question or "")
    return int(m.group(1)) if m else 1


def _apply_guardrail(answer, trace, question):
    info = _parse_trace(trace)
    up, ship = info.get("unit_price"), info.get("shipping")
    # only act on a COMPLETE, valid order (stock + numeric shipping). Otherwise leave
    # the model's answer (price/stock query, out-of-stock, or unserved -> its refusal).
    if not info.get("found") or not info.get("in_stock"):
        return answer
    if not isinstance(up, (int, float)) or not isinstance(ship, (int, float)):
        return answer
    qty = _order_qty(info, question)
    sq = info.get("stock_qty")
    if isinstance(sq, (int, float)) and qty > sq:
        return answer  # can't fulfill quantity -> keep model's refusal
    pct = info.get("pct") or 0
    total = (int(up) * qty * (100 - pct)) // 100 + int(ship)
    line = f"Tong cong: {total} VND"
    if isinstance(answer, str) and re.search(r"(?i)t[ổo]ng\s*c[ộo]ng", answer):
        # keep the model's wording, just correct the number
        return re.sub(r"(?i)(t[ổo]ng\s*c[ộo]ng\s*:?\s*)[\d][\d.,]*(\s*vnd)",
                      rf"\g<1>{total}\g<2>", answer, count=1)
    return line  # model refused a valid order (over-refusal) -> supply correct total


def mitigate(call_next, question, config, context):
    cid = new_correlation_id()
    if cid:
        set_correlation_id(cid)

    cache = context.get("cache")
    lock = context.get("cache_lock")

    # 1) sanitize input (light injection defense; prompt is the primary defense)
    clean_q = _sanitize(question)

    # 2) prompt routing -- force our better system prompt on every request
    conf = dict(config)
    if _SYSTEM_PROMPT:
        conf["system_prompt"] = _SYSTEM_PROMPT

    cache_key = (clean_q, conf.get("system_prompt", ""), conf.get("model"))

    # 3) cache lookup (concurrent run -> guard shared state)
    if cache is not None and lock is not None:
        with lock:
            hit = cache.get(cache_key)
        if hit is not None:
            if logger:
                logger.log_event("CACHE_HIT", {"qid": context.get("qid")})
            return hit

    # 4) retry loop with backoff on failures / exceptions
    rcfg = config.get("retry") or {}
    attempts = max(int(rcfg.get("max_attempts", 1) or 1), 2)
    backoff_ms = int(rcfg.get("backoff_ms", 250) or 250)

    result = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": [], "meta": {}}
    t0 = time.time()
    for i in range(attempts):
        rate_limited = False
        try:
            result = call_next(clean_q, conf)
        except Exception as e:  # never let observability/mitigation crash the run
            result = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": [], "meta": {}}
            msg = repr(e)
            rate_limited = ("429" in msg) or ("rate limit" in msg.lower())
            if logger:
                logger.log_event("CALL_EXCEPTION", {"qid": context.get("qid"), "attempt": i,
                                                     "rate_limited": rate_limited, "error": msg})
        if not _bad(result):
            break
        if i < attempts - 1:
            # exponential backoff (capped). 429/TPM resets each minute, so wait longer.
            wait = (backoff_ms / 1000.0) * (2 ** i)
            if rate_limited:
                wait = max(wait, 8.0)
            time.sleep(min(wait, 20.0))
    wall_ms = int((time.time() - t0) * 1000)

    if not isinstance(result, dict):
        result = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": [], "meta": {}}

    # 5) arithmetic guardrail -- recompute exact total from the tools' actual outputs
    orig_answer = result.get("answer")
    fixed = _apply_guardrail(orig_answer, result.get("trace"), clean_q)
    guardrail_fired = fixed != orig_answer
    if guardrail_fired:
        result["answer"] = fixed

    # 6) output redaction (defense in depth on top of config.redact_pii)
    ans = result.get("answer")
    pii_hits = 0
    if isinstance(ans, str):
        red, pii_hits = redact(ans)
        if pii_hits:
            result["answer"] = red

    # 6b) normalize a total answer to exactly one clean line (no trailing PII/prose).
    # Keeps the scorer's parser happy and removes any echoed contact info entirely.
    ans = result.get("answer")
    if isinstance(ans, str):
        m = re.search(r"(?i)t[ổo]ng\s*c[ộo]ng\s*:?\s*([\d][\d.,]*)\s*vnd", ans)
        if m:
            num = re.sub(r"[.,]", "", m.group(1))
            result["answer"] = f"Tong cong: {num} VND"

    # 7) OBSERVABILITY -- the only place these signals exist
    meta = result.get("meta", {}) or {}
    usage = meta.get("usage", {}) or {}
    tools = meta.get("tools_used", []) or []
    if logger:
        logger.log_event("AGENT_CALL", {
            "qid": context.get("qid"),
            "session": context.get("session_id"),
            "turn": context.get("turn_index"),
            "status": result.get("status"),
            "steps": result.get("steps"),
            "latency_ms": meta.get("latency_ms"),
            "wall_ms": wall_ms,
            "usage": usage,
            "cost_usd": cost_from_usage(meta.get("model", ""), usage),
            "model": meta.get("model"),
            "tools_used": tools,
            "n_tools": len(tools),
            "pii_redacted_from_answer": pii_hits,
            "guardrail_fired": guardrail_fired,
            "answer_original": orig_answer,
            "answer": result.get("answer"),
            "trace": result.get("trace"),
        })

    # 8) cache successful results only
    if result.get("status") == "ok" and cache is not None and lock is not None:
        with lock:
            cache[cache_key] = result

    return result
