"""Evaluate the policy graph against passage retrieval on questions that need several facts.

    python -m evaluation.graph_eval [--db PATH] [--out results/graph_retrieval.md]

The questions are in evaluation/graph_queries.json: 9 dev questions, used while the graph's recognition of
questions was built, and 23 test questions written afterwards, in six types (routing an amount to a role,
changes between versions, what checks a rule, sets of rules, amounts that need several rules, and single-step
questions). For each question and method the context a model would be given is assembled, and measured:

    evidence  complete when every passage the question lists (a rule's, or the section text with the approval
              limits, in the version named) is in the context
    derived   for the graph, whether its facts state the answer the question asks for, checked against their
              values (the role an amount needs, what changed, what checks a rule, the members of a set). Passage
              retrieval states no derived answer: the reader must work it out from the passages
    size      the mean number of passages and of characters in the context

Methods (five passages where a method ranks passages):
    lexical                the application's ranker over the active version's documents
    lexical, all versions  the same ranker over every version's passages
    dense, hybrid          with an embedding model, over the active version
    graph                  the graph's facts and the passages they cite (at most six)
    graph + lexical        what Ask AI is given: the graph's passages first, then the ranker's
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from auditiq import db
from auditiq.policy_graph import Fact, PolicyGraph, merge_passages
from auditiq.retrieval import EndpointEmbedder, Hit, PolicyIndex

QUERIES = Path(__file__).with_name("graph_queries.json")
SPLITS = ["dev", "test"]
TYPES = ["routing", "change", "checker", "set", "multi", "single"]
K = 5


def load_queries(path: Path = QUERIES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def covers(passages: list[Hit], key: str, version: str) -> bool:
    """Whether a passage of rule ``key`` (or the text of section ``key``) in ``version`` is among the passages."""
    for hit in passages:
        if hit.version != version:
            continue
        if hit.clause_id == key or (hit.clause_id is None and hit.section.split(" ", 1)[0].rstrip(".") == key):
            return True
    return False


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def derived(answer: dict | None, facts: list[Fact]) -> bool | None:
    """Whether the facts state the answer; None for a question that asks for none."""
    if answer is None:
        return None
    checks = []
    lowest = [f.data for f in facts if f.kind == "routing" and "lowest" in f.data]
    verdicts = [f.data for f in facts if f.kind == "routing" and "allowed" in f.data]
    changes = [f.data for f in facts if f.kind == "change" and f.data]
    if "lowest" in answer:
        checks.append(bool(lowest) and all(r["lowest"] == answer["lowest"] for r in lowest))
    if "role" in answer:
        checks.append(any(v["role"] == answer["role"] and v["allowed"] == answer["allowed"] for v in verdicts))
    if "band" in answer:
        checks.append(any(f.kind == "band" and f.data.get("clause") == answer["band"] for f in facts))
    if "changes" in answer:
        found = {(c["clause"], c["parameter"], c["role"], _num(c["from"]), _num(c["to"]))
                 for c in changes if not c.get("unchanged")}
        gold = {(c, p, r, _num(a), _num(b)) for c, p, r, a, b in answer["changes"]}
        checks.append(found == gold)
    if "unchanged" in answer:
        same = {c["clause"] for c in changes if c.get("unchanged")}
        moved = {c["clause"] for c in changes if not c.get("unchanged")}
        checks.append(set(answer["unchanged"]) <= same and not set(answer["unchanged"]) & moved)
    if "no_change_of_role" in answer:
        checks.append(not any(c.get("role") == answer["no_change_of_role"] for c in changes) and bool(changes))
    if "checker" in answer:
        checks.append(all(any(f.kind == "rule" and f.data.get("clause") == clause and f.data.get("checker") == checker
                              for f in facts) for clause, checker in answer["checker"].items()))
    if "members" in answer:
        checks.append(any(sorted(f.data["members"]) == sorted(answer["members"]) for f in facts if "members" in f.data))
    if "clauses" in answer:
        checks.append(set(answer["clauses"]) <= {f.data.get("clause") for f in facts if f.kind == "rule"})
    return all(checks)


def all_versions_index(conn: db.Database) -> PolicyIndex:
    """The lexical ranker over the passages of every version, for the baseline that may see them all."""
    rows = conn.execute("SELECT c.*, d.file_name FROM policy_chunks c JOIN policy_documents d ON d.doc_id = c.doc_id "
                        "ORDER BY d.doc_id, c.position").fetchall()
    chunks = [{**dict(r), "embedding": np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"] else None}
              for r in rows]
    return PolicyIndex(chunks)


def contexts(question: str, graph: PolicyGraph, lexical: PolicyIndex, everything: PolicyIndex,
             dense: PolicyIndex | None) -> dict[str, tuple[list[Hit], list[Fact]]]:
    """The context each method gives a model for one question: its passages and its facts."""
    out = {"lexical": (lexical.search(question, k=K, mode="lexical"), []),
           "lexical, all versions": (everything.search(question, k=K, mode="lexical"), [])}
    if dense is not None:
        for mode in ("dense", "hybrid"):
            out[mode] = (dense.search(question, k=K, mode=mode), [])
    linked = graph.query(question, lexical)
    out["graph"] = (linked.passages, linked.facts)
    out["graph + lexical"] = (merge_passages(linked.passages, out["lexical"][0], K), linked.facts)
    return out


def evaluate(conn: db.Database, queries: list[dict], embedder=None) -> dict:
    graph = PolicyGraph.from_db(conn)
    lexical = PolicyIndex.from_db(conn, version=graph.version)
    everything = all_versions_index(conn)
    dense = None
    if embedder is not None:
        candidate = PolicyIndex.from_db(conn, version=graph.version, embedder=embedder)
        dense = candidate if "dense" in candidate.modes else None
    rows = []
    for q in queries:
        for method, (passages, facts) in contexts(q["question"], graph, lexical, everything, dense).items():
            rows.append({"id": q["id"], "split": q["split"], "type": q["type"], "method": method,
                         "evidence": all(covers(passages, key, version) for key, version in q["evidence"]),
                         "missing": [f"{key}@{version}" for key, version in q["evidence"] if not covers(passages, key, version)],
                         "derived": derived(q["answer"], facts) if method.startswith("graph") else None,
                         "passages": len(passages),
                         "characters": sum(len(h.text) for h in passages) + sum(len(f.text) for f in facts)})
    return {"version": graph.version, "versions": [v["version"] for v in graph.versions],
            "methods": list(dict.fromkeys(r["method"] for r in rows)), "rows": rows,
            "embedding": embedder.name if dense is not None else None}


def summary(rows: list[dict]) -> dict:
    asked = [r for r in rows if r["derived"] is not None]
    return {"n": len(rows), "evidence": sum(r["evidence"] for r in rows),
            "derived": sum(r["derived"] for r in asked), "derived_n": len(asked),
            "passages": sum(r["passages"] for r in rows) / len(rows) if rows else 0.0,
            "characters": sum(r["characters"] for r in rows) / len(rows) if rows else 0.0}


def render(result: dict, queries: list[dict]) -> str:
    rows, methods = result["rows"], result["methods"]
    n = {s: sum(q["split"] == s for q in queries) for s in SPLITS}
    lines = [f"Policy graph against passage retrieval on {len(queries)} questions about policy v{result['version']} "
             f"(versions stored: {', '.join('v' + v for v in result['versions'])}): {n['dev']} dev questions, used while "
             f"the graph's recognition of questions was built, and {n['test']} test questions written afterwards. "
             + (f"Embedding model: `{result['embedding']}`. " if result["embedding"] else "No embedding model. ")
             + "Evidence: every passage the question rests on is in the context. Derived: the graph's facts state the "
               "answer, checked against their values (passage retrieval states none). Questions written by the authors.",
             "", "| Method | Questions | Evidence complete | Derived answer stated | Passages | Characters |",
             "|---|---|---|---|---|---|"]
    for split in SPLITS:
        for method in methods:
            s = summary([r for r in rows if r["method"] == method and r["split"] == split])
            derived_text = f"{s['derived']}/{s['derived_n']}" if method.startswith("graph") else "–"
            lines.append(f"| {method} | {split} | {s['evidence']}/{s['n']} | {derived_text} | {s['passages']:.1f} | "
                         f"{s['characters']:.0f} |")
    lines += ["", "Test questions by type (evidence complete; derived answer for the graph methods):", "",
              "| Method | " + " | ".join(TYPES) + " |", "|---|" + "---|" * len(TYPES)]
    for method in methods:
        cells = []
        for kind in TYPES:
            subset = [r for r in rows if r["method"] == method and r["split"] == "test" and r["type"] == kind]
            if not subset:
                cells.append("–")
                continue
            s = summary(subset)
            cell = f"{s['evidence']}/{s['n']}"
            if method.startswith("graph") and s["derived_n"]:
                cell += f"; {s['derived']}/{s['derived_n']}"
            cells.append(cell)
        lines.append(f"| {method} | " + " | ".join(cells) + " |")
    misses = [r for r in rows if r["split"] == "test" and r["method"] in ("graph", "graph + lexical")
              and (not r["evidence"] or r["derived"] is False)]
    lines += ["", "Test questions the graph methods did not fully answer:" if misses else
              "The graph methods answered every test question completely.", ""]
    for r in misses:
        what = []
        if not r["evidence"]:
            what.append("missing " + ", ".join(r["missing"]))
        if r["derived"] is False:
            what.append("derived answer not stated")
        lines.append(f"- {r['id']} ({r['type']}, {r['method']}): {'; '.join(what)}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    conn = db.connect(args.db)
    queries = load_queries()
    result = evaluate(conn, queries, EndpointEmbedder.from_env())
    text = render(result, queries)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        args.out.with_suffix(".json").write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
