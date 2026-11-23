"""Pre-registration and offline evidence worksheets. A reviewer supplies semantic judgements."""
import csv
import io

from prompt_builder import DIMENSIONS
from storage import attempt_key, dump_json, dump_text, read_json
from validators import body_and_refs, CITE

MAIN = [f"{cid}_{aud}" for cid in "AB" for aud in ("customers", "candidates")]
VERDICTS = ["Supported", "Partially supported", "Unsupported", "Contradicted by source"]
CRITERIA = {
    "Factual faithfulness": "Check material statements against the supplied excerpts, including qualifiers and missing details.",
    "Audience relevance": "Identify specific advice that helps a prospective customer decide what to ask or do.",
    "Information coverage": "Compare coverage of problem, offering, use, customer segment and open questions.",
    "Clarity": "Compare section order, specificity and how easily a reader can find decision-relevant information.",
}
PROTOCOL = dict(dimensions=DIMENSIONS, sample="First two material factual claims in reading order per main brochure, including uncited claims. Split compound claims in reading order. Exclude headings, questions and advice without factual propositions. Record a deficiency if fewer than two.",
                verdicts=VERDICTS, criteria=CRITERIA, pair=["A_customers", "baseline"], reviewer="human review required")
FIELDS = ["brochure", "ordinal", "claim", "source_id", "source_url", "excerpt", "verdict", "explanation", "deficiency"]


def read_text(path):
    return path.read_bytes().decode("utf-8")


def write_rows(path, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    dump_text(path, output.getvalue())


def accepted_text(root, name):
    metadata = read_json(root / "metadata" / f"{name}.json")
    key = attempt_key(name, metadata.get("accepted_attempt", 1))
    return read_text(root / "responses" / f"{key}.txt")


def prepare_review(root):
    directory = root / "review"
    evidence = []
    rows = []
    for name in MAIN:
        body, _ = body_and_refs(accepted_text(root, name))
        context = read_json(root / "contexts" / f"{name}.json")
        evidence.append(f"## {name}\n\n{body}\n")
        for item in context["evidence"]:
            evidence.append(f"### {item['source_id']} — {item['url']}\n\n{item['text']}\n")
        rows.extend(dict(brochure=name, ordinal=i) for i in (1, 2))
    dump_text(directory / "evidence.md", "\n".join(evidence))
    if not (directory / "claim_audit.csv").exists():
        write_rows(directory / "claim_audit.csv", rows)
    paired = ["# Controlled prompt experiment", "Read both outputs and the shared context. For each criterion enter exact examples from each output, then explain the difference, tie or trade-off."]
    for name in ("A_customers", "baseline"):
        attempts = read_json(root / "metadata" / f"{name}.json").get("accepted_attempt", 1)
        paired.append(f"## {name} · accepted attempt {attempts}\n\n" + accepted_text(root, name))
    for key, detail in CRITERIA.items():
        paired.append(f"## {key}\n\n{detail}\n\nReviewer findings pending.")
    dump_text(directory / "paired_evidence.md", "\n\n".join(paired))
    if not (directory / "experiment.json").exists():
        dump_json(directory / "experiment.json", {key: {"improved_excerpt": "", "baseline_excerpt": "",
                                                        "finding": ""} for key in CRITERIA})


def verify_review(root):
    with (root / "review/claim_audit.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    expected = [(n, str(i)) for n in MAIN for i in (1, 2)]
    if [(r["brochure"], r["ordinal"]) for r in rows] != expected:
        raise ValueError("expected two ordered audit entries per brochure")
    for r in rows:
        if r["deficiency"].strip() and not r["claim"].strip():
            continue
        name = r["brochure"]
        body, _ = body_and_refs(accepted_text(root, name))
        if not r["claim"].strip() or r["claim"] not in body or r["verdict"] not in VERDICTS or not r["explanation"].strip():
            raise ValueError(f"incomplete audit for {name}")
        if not r["source_id"]:
            if r["verdict"] != "Unsupported" or r["source_url"] or r["excerpt"]:
                raise ValueError("uncited claim requires explicit unsupported verdict")
            continue
        entries = read_json(root / "contexts" / f"{name}.json")["evidence"]
        if r["source_id"] not in CITE.findall(body) or not any(
                s["source_id"] == r["source_id"] and s["url"] == r["source_url"]
                and ((r["excerpt"] and r["excerpt"] in s["text"]) or
                     (not r["excerpt"] and r["verdict"] == "Unsupported")) for s in entries):
            raise ValueError(f"check evidence excerpt and source for {name}")
    return len(rows)


def publish_review(root):
    """Publish reviewed evidence alongside immutable model responses."""
    count = verify_review(root)
    notes = read_json(root / "review/experiment.json")
    originals = {key: body_and_refs(accepted_text(root, name))[0]
                 for key, name in (("improved_excerpt", "A_customers"), ("baseline_excerpt", "baseline"))}
    if set(notes) != set(CRITERIA):
        raise ValueError("review all four predefined criteria")
    sections = ["# Controlled comparison of two prompts", f"Run: {root.name}. Company A, prospective customers."]
    for name in ("A_customers", "baseline"):
        attempt = read_json(root / "metadata" / f"{name}.json").get("accepted_attempt", 1)
        sections.append(f"{name}: accepted attempt {attempt}. The original requests and all samples are retained.")
    for criterion in CRITERIA:
        row = notes[criterion]
        if not isinstance(row.get("finding"), str) or not row["finding"].strip() or any(
                not row.get(key) or row[key] not in original for key, original in originals.items()):
            raise ValueError(f"{criterion}: supply exact paired quotations and a finding")
        sections.append(f"## {criterion}\n\nImproved: {row['improved_excerpt']}\n\nBaseline: {row['baseline_excerpt']}\n\n{row['finding']}")
    dump_text(root / "artifacts/prompt_experiment.md", "\n\n".join(sections))
    dump_text(root / "artifacts/claim_audit.csv", read_text(root / "review/claim_audit.csv"))
    return count

