"""Evaluate policy retrieval on a fixed set of questions.

    python -m evaluation.retrieval_eval [--rewrite] [--db PATH] [--out results/retrieval.md]

For each question in evaluation/retrieval_queries.json the index is searched
and the rank of the clause that answers it is recorded. Reported per ranker:
recall at 1 and at 3 and the mean reciprocal rank.

The questions come in three groups of 16, one per clause in each group:
    wording           the question reuses the policy's terms
    paraphrase (dev)  the first paraphrase of each clause; any choice between
                      rankers (the default of `mode="auto"`) is made on these
    paraphrase (test) the second paraphrase of each clause; never used to choose

Rankers: lexical always; dense and hybrid when an embedding model is configured
and the passages are embedded; with --rewrite, each of them again on questions
that the chat model has restated in the documents' vocabulary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from auditiq import db
from auditiq.llm import ChatClient, LLMSettings, OpenAIChatClient, ResponseCache
from auditiq.retrieval import EndpointEmbedder, PolicyIndex

QUERIES = Path(__file__).with_name("retrieval_queries.json")
GROUPS = ["wording", "paraphrase (dev)", "paraphrase (test)"]


def load_queries(path: Path = QUERIES) -> list[dict]:
    """The questions, each tagged with its group. The first paraphrase of a clause is dev, the second test."""
    queries = json.loads(path.read_text(encoding="utf-8"))["queries"]
    seen: dict[str, int] = {}
    out = []
    for q in queries:
        if q["kind"] == "wording":
            group = "wording"
        else:
            seen[q["clause"]] = seen.get(q["clause"], 0) + 1
            group = "paraphrase (dev)" if seen[q["clause"]] == 1 else "paraphrase (test)"
        out.append({**q, "group": group})
    return out


def rank_of(index: PolicyIndex, query: str, clause: str, mode: str, client: ChatClient | None = None) -> int | None:
    """1-based rank of the clause chunk among all chunks, or None if it is not indexed."""
    for rank, hit in enumerate(index.search(query, k=len(index.chunks), mode=mode, client=client), start=1):
        if hit.clause_id == clause:
            return rank
    return None


def evaluate(index: PolicyIndex, queries: list[dict], client: ChatClient | None = None) -> dict:
    rankers = [(mode, None) for mode in index.modes]
    if client is not None:
        rankers += [(mode, client) for mode in index.modes]
    out = {}
    for mode, rewriter in rankers:
        name = f"{mode} + rewrite" if rewriter else mode
        ranks = [(q["group"], rank_of(index, q["query"], q["clause"], mode, rewriter)) for q in queries]
        for group in GROUPS:
            subset = [r for g, r in ranks if g == group]
            n = len(subset)
            out[(name, group)] = {
                "n": n,
                "recall_at_1": sum(r == 1 for r in subset) / n,
                "recall_at_3": sum(r is not None and r <= 3 for r in subset) / n,
                "mrr": sum(1 / r for r in subset if r) / n,
            }
    return out


def render(results: dict, index: PolicyIndex, chat_model: str | None = None) -> str:
    embed = index.embedder.name if index.embedder is not None and "dense" in index.modes else None
    lines = [f"Policy retrieval over {len(index.chunks)} passages, 16 questions per group. "
             + (f"Embedding model: `{embed}`. " if embed else "No embedding model configured. ")
             + (f"Question rewriting by `{chat_model}`. " if chat_model else "")
             + f"Default ranking of the application: {index.default_mode()} for a question as asked, "
               f"{index.default_mode(restated=True)} for a restated one.",
             "", "| Ranker | Questions | Recall@1 | Recall@3 | MRR |", "|---|---|---|---|---|"]
    for (name, group), m in results.items():
        lines.append(f"| {name} | {group} | {m['recall_at_1']:.3f} | {m['recall_at_3']:.3f} | {m['mrr']:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--rewrite", action="store_true", help="also evaluate with questions restated by the chat model")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    conn = db.connect(args.db)
    index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
    client = OpenAIChatClient(LLMSettings.from_env(), ResponseCache()) if args.rewrite else None
    text = render(evaluate(index, load_queries(), client), index, client.model if client else None)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
