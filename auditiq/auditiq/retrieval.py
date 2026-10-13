"""Retrieval over the ingested policy documents.

Two rankers and their fusion:

    lexical  TF-IDF over words and character n-grams. Always available; finds a
             passage that shares wording with the question.
    rewrite  the lexical ranker on a question that the chat model has first
             restated in the documents' vocabulary. Needs the chat model only.
    dense    cosine similarity of embeddings from an embedding model. Finds a
             passage that means the same in other words. Needs a model, served
             by any OpenAI-compatible /embeddings endpoint:
                 AUDITIQ_EMBED_MODEL      e.g. nomic-embed-text
                 AUDITIQ_EMBED_BASE_URL   default: AUDITIQ_LLM_BASE_URL
                 AUDITIQ_EMBED_API_KEY    default: AUDITIQ_LLM_API_KEY
    hybrid   reciprocal rank fusion of the two; the default when embeddings exist.

Without an embedding model the index is lexical only, and says so.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import load_env
from .db import Database
from .llm import ChatClient, extract_json
from .policy import PROJECT_ROOT

RRF_K = 60
# The ranking `mode="auto"` uses when the passages are embedded: dense for the
# question as asked, hybrid for a question the chat model has restated. Both
# were chosen on the development half of the paraphrased questions and are
# reported on the other half (evaluation/retrieval_eval.py, results/retrieval.md).
DEFAULT_WITH_EMBEDDINGS = {"as asked": "dense", "restated": "hybrid"}
RULE_TITLE = re.compile(r"^Rule [\d.]+ \(\w+\), (.+?)\.")
SECTION_NUMBER = re.compile(r"^[\d.]+\s+")

REWRITE_SYSTEM = """\
You help an auditor search a set of policy documents. The documents use formal wording; the auditor may not. The titles of the sections and rules of the documents are:
{titles}

Restate the auditor's question in the formal wording such documents use, and name the listed titles most likely to answer it (three at most).

Reply with one JSON object and nothing else:
{"restatement": "<the question in formal wording>", "titles": ["<title>", "<title>"]}"""


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], kind: str = "document") -> np.ndarray: ...


def normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class EndpointEmbedder:
    """Embeddings from POST {base_url}/embeddings (OpenAI-compatible)."""

    def __init__(self, base_url: str, model: str, api_key: str = "", query_prefix: str = "",
                 document_prefix: str = "", timeout: float = 300.0, transport: httpx.BaseTransport | None = None):
        self.name = model
        self.prefix = {"query": query_prefix, "document": document_prefix}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, env_file: Path | None = PROJECT_ROOT / ".env") -> "EndpointEmbedder | None":
        """The configured embedder, or None when no embedding model is set."""
        load_env(env_file)
        model = os.environ.get("AUDITIQ_EMBED_MODEL")
        base_url = os.environ.get("AUDITIQ_EMBED_BASE_URL") or os.environ.get("AUDITIQ_LLM_BASE_URL")
        if not model or not base_url:
            return None
        return cls(base_url, model,
                   api_key=os.environ.get("AUDITIQ_EMBED_API_KEY") or os.environ.get("AUDITIQ_LLM_API_KEY", ""),
                   query_prefix=os.environ.get("AUDITIQ_EMBED_QUERY_PREFIX", ""),
                   document_prefix=os.environ.get("AUDITIQ_EMBED_DOCUMENT_PREFIX", ""))

    def embed(self, texts: list[str], kind: str = "document") -> np.ndarray:
        reply = self._http.post("/embeddings", json={"model": self.name,
                                                     "input": [self.prefix[kind] + t for t in texts]})
        if reply.status_code != 200:
            raise RuntimeError(f"embedding request failed (HTTP {reply.status_code}: {reply.text[:200]})")
        data = sorted(reply.json()["data"], key=lambda item: item["index"])
        return normalize(np.array([item["embedding"] for item in data]))


@dataclass
class Hit:
    chunk_id: int
    document: str
    version: str | None
    kind: str
    clause_id: str | None
    section: str
    page: int
    text: str
    score: float
    lexical_rank: int
    dense_rank: int | None = None

    @property
    def source(self) -> str:
        label = f"Rule {self.clause_id}" if self.clause_id else self.section
        return f"{label} ({self.document}, page {self.page})"


def chunk_text(row) -> str:
    """What is indexed for a chunk: its section heading and its text."""
    return f"{row['section']}. {row['text']}"


class PolicyIndex:
    """The chunks of one policy version plus the documents that carry no policy version."""

    def __init__(self, chunks: list[dict], embedder: Embedder | None = None):
        if not chunks:
            raise ValueError("no policy document has been ingested")
        self.chunks = chunks
        self.embedder = embedder
        texts = [chunk_text(c) for c in chunks]
        self._words = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), stop_words="english").fit(texts)
        self._chars = TfidfVectorizer(sublinear_tf=True, analyzer="char_wb", ngram_range=(3, 5)).fit(texts)
        self._word_matrix = self._words.transform(texts)
        self._char_matrix = self._chars.transform(texts)
        vectors = [c.get("embedding") for c in chunks]
        usable = embedder is not None and all(v is not None for v in vectors) and \
            all(c.get("embed_model") == embedder.name for c in chunks)
        self._dense = np.vstack(vectors) if usable else None

    @classmethod
    def from_db(cls, conn: Database, version: str | None = None,
                embedder: Embedder | None = None) -> "PolicyIndex":
        """Index the chunks of ``version`` (default: the active policy) and of the other documents."""
        if version is None:
            row = conn.execute("SELECT version FROM company_policies WHERE is_active = 1").fetchone()
            version = row["version"] if row else None
        rows = conn.execute(
            "SELECT c.*, d.file_name FROM policy_chunks c JOIN policy_documents d ON d.doc_id = c.doc_id "
            "WHERE c.version IS NULL OR c.version = ? ORDER BY d.doc_id, c.position", (version,)).fetchall()
        chunks = []
        for r in rows:
            chunk = dict(r)
            chunk["embedding"] = np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"] else None
            chunks.append(chunk)
        return cls(chunks, embedder)

    @property
    def modes(self) -> list[str]:
        return ["lexical", "dense", "hybrid"] if self._dense is not None else ["lexical"]

    def default_mode(self, restated: bool = False) -> str:
        """The ranking used by ``mode='auto'``; see DEFAULT_WITH_EMBEDDINGS."""
        if self._dense is None:
            return "lexical"
        return DEFAULT_WITH_EMBEDDINGS["restated" if restated else "as asked"]

    def _lexical_scores(self, query: str) -> np.ndarray:
        words = (self._word_matrix @ self._words.transform([query]).T).toarray().ravel()
        chars = (self._char_matrix @ self._chars.transform([query]).T).toarray().ravel()
        return 0.5 * words + 0.5 * chars

    @property
    def titles(self) -> list[str]:
        """Section headings and rule titles of the indexed documents, in order, without duplicates."""
        found = []
        for c in self.chunks:
            rule = RULE_TITLE.match(c["text"]) if c["kind"] == "clause" else None
            found.append(rule.group(1) if rule else SECTION_NUMBER.sub("", c["section"]))
        return list(dict.fromkeys(t for t in found if t))

    def rewrite(self, query: str, client: ChatClient) -> str:
        """Restate a question in the vocabulary of the documents, with the help of the model.

        The model sees the question and the titles of the indexed sections and
        rules, not their text. Its restatement is appended to the question, so
        that the lexical ranker can match a question asked in other words.
        Returns the question unchanged when the model gives no usable reply.
        """
        system = REWRITE_SYSTEM.replace("{titles}", "\n".join(f"- {t}" for t in self.titles))
        reply = client.complete([{"role": "system", "content": system}, {"role": "user", "content": query}])
        try:
            data = extract_json(reply.text)
        except ValueError:
            return query
        parts = [p for key in ("restatement", "titles") for p in (data.get(key) if isinstance(data.get(key), list)
                                                                   else [data.get(key)]) if isinstance(p, str)]
        return " ".join([query, *parts])

    def search(self, query: str, k: int = 5, mode: str = "auto", client: ChatClient | None = None) -> list[Hit]:
        """The ``k`` chunks that best answer ``query``.

        ``mode``: auto, lexical, dense or hybrid. With ``client`` the question
        is first restated in the documents' vocabulary (see ``rewrite``).
        """
        if mode == "auto":
            mode = self.default_mode(restated=client is not None)
        if mode not in self.modes:
            raise ValueError(f"mode {mode!r} is not available; this index supports {self.modes}")
        if client is not None:
            query = self.rewrite(query, client)
        lexical = self._lexical_scores(query)
        lexical_rank = np.empty(len(lexical), dtype=int)
        lexical_rank[np.argsort(-lexical, kind="stable")] = np.arange(1, len(lexical) + 1)
        dense_rank = None
        if mode == "lexical":
            score = lexical
        else:
            dense = self._dense @ self.embedder.embed([query], kind="query")[0]
            dense_rank = np.empty(len(dense), dtype=int)
            dense_rank[np.argsort(-dense, kind="stable")] = np.arange(1, len(dense) + 1)
            score = dense if mode == "dense" else 1 / (RRF_K + lexical_rank) + 1 / (RRF_K + dense_rank)
        hits = []
        for i in np.argsort(-score, kind="stable")[:k]:
            c = self.chunks[i]
            hits.append(Hit(c["chunk_id"], c["file_name"], c["version"], c["kind"], c["clause_id"], c["section"],
                            c["page"], c["text"], float(score[i]), int(lexical_rank[i]),
                            int(dense_rank[i]) if dense_rank is not None else None))
        return hits


def embed_chunks(conn: Database, embedder: Embedder, batch: int = 16) -> int:
    """Compute and store the embedding of every chunk that lacks one from this model."""
    rows = conn.execute("SELECT chunk_id, section, text FROM policy_chunks "
                        "WHERE embedding IS NULL OR embed_model IS DISTINCT FROM ?", (embedder.name,)).fetchall()
    for start in range(0, len(rows), batch):
        part = rows[start:start + batch]
        vectors = embedder.embed([chunk_text(r) for r in part], kind="document")
        conn.executemany("UPDATE policy_chunks SET embedding = ?, embed_model = ? WHERE chunk_id = ?",
                         [(v.astype(np.float32).tobytes(), embedder.name, r["chunk_id"]) for v, r in zip(vectors, part)])
    conn.commit()
    return len(rows)
