"""Deterministic max-min allocation over eligible source text. One pool for any set of sources."""
import json


def build_context(sources, budget):
    if budget < 1:
        raise ValueError("positive budget required")
    lengths = [len(s["text"]) if s["status"] == "ok" and s["text"].strip() else 0 for s in sources]
    grants = [0] * len(sources)
    left = budget
    active = [i for i, n in enumerate(lengths) if n]
    while active and left:
        share = max(1, left // len(active))
        for i in active:
            grant = min(share, lengths[i]-grants[i], left)
            grants[i] += grant
            left -= grant
        active = [i for i in active if grants[i] < lengths[i]]
    evidence, decisions = [], []
    for source, size in zip(sources, grants):
        if size:
            evidence.append({**{k: source[k] for k in ("source_id", "company_id", "title", "url")},
                             "text": source["text"][:size]})
        full = len(source["text"])
        state = "omitted" if not size else "included" if size == full else "truncated"
        reason = source["status"] if source["status"] != "ok" else "empty text" if not source["text"].strip() else (
            "full source" if state == "included" else "shared character budget")
        decisions.append(dict(source_id=source["source_id"], state=state, reason=reason,
                              original_chars=full, supplied_chars=size))
    return dict(budget=budget, evidence=evidence, decisions=decisions,
                text=json.dumps(evidence, ensure_ascii=False, indent=2))

