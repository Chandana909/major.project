"""The policy as a knowledge graph, and retrieval over it for Ask AI.

The graph is built by code from what the store already holds exactly: the clause registry of each policy
version (title, severity, kind, parameters), the passages of the ingested documents with their pages, and the
code that checks each clause (the control function that names it, or the agent whose remit covers it).
Nothing in it is extracted by a model, so it can be wrong only where the registry or the documents are.

    nodes   the version, its sections and clauses, the clauses' parameters, the roles of the approval limits,
            the control functions and agents that check the clauses, the document pages that state them,
            and the other stored versions
    edges   version -has section-> section -has rule-> clause -sets-> parameter -limit-> role;
            clause -checked by-> control or agent; clause or parameter -stated on-> page;
            other version -changes-> parameter (or clause) where it differs from the version drawn

``PolicyGraph.query(question)`` recognises what a question names (rule numbers, versions, roles, amounts,
checkers, severities, kinds and the topics of the rules) and follows the edges from there. It returns facts,
each citing the rule and version it comes from and the passage that states it, and the passages themselves.
Some facts are derived from several edges at once, which passage retrieval leaves to the reader: the lowest
role whose limit covers an amount, an amount in the band rule 4.1.2's guide names for structuring, an amount
that is a round multiple (4.3.1), and what changed between two versions.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field

from . import controls, db
from .agents import AGENTS
from .retrieval import Hit, PolicyIndex

CLAUSE_ID = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.]*\d)")
VERSION = re.compile(r"(?<![\d.])v?(\d+\.\d+)(?!\.?\d)", re.IGNORECASE)
AMOUNT = re.compile(
    r"(?P<cur>₹|\brs\.?|\binr\b|\brupees?\b)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>lakhs?\b|lacs?\b|l\b|crores?\b|cr\b|k\b|thousand\b|million\b|mn\b)?\s*(?P<cur2>rupees?\b|inr\b)?",
    re.IGNORECASE)
UNITS = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7,
         "k": 1e3, "thousand": 1e3, "million": 1e6, "mn": 1e6}
CHANGE_WORDS = re.compile(r"\b(chang\w*|differ\w*|compar\w*|between|versus|vs\.?|revis\w*|updat\w*|new|old|"
                          r"increas\w*|decreas\w*|rais\w*|lower\w*)\b", re.IGNORECASE)
SEVERITY_WORDS = [re.compile(r"\b(critical|high|medium|low)\b(?=[\w\s-]{0,24}\b(rules?|clauses?)\b)", re.IGNORECASE),
                  re.compile(r"\b(?:rules?|clauses?)\b[\w\s-]{0,16}?\b(critical|high|medium|low)\b", re.IGNORECASE)]
SET_INTENT = re.compile(r"\b(which|list|all|what)\b.*\brules\b|\brules\b.*\b(are|does|do)\b", re.IGNORECASE)
JUDGEMENT_WORDS = re.compile(r"\b(judgement|judgment|agents?|models?|llm|language model)\b", re.IGNORECASE)
CONTROL_WORDS = re.compile(r"\b(code|controls?|deterministic|automatic\w*)\b", re.IGNORECASE)
ROLE_SYNONYMS = {"chief financial officer": "CFO"}
# Words of the rules' titles that name no rule by themselves: they occur in questions of every kind.
GENERIC = {"amount", "match", "vendor", "date", "days", "code", "state", "same", "across", "near", "exact"}


@dataclass
class Fact:
    """A statement taken or derived from the graph, with the rule and version it rests on and its passage."""
    text: str
    kind: str                       # rule, parameter, limit, routing, band, round, change, checker, set
    version: str
    clause: str | None = None
    passage: Hit | None = None
    data: dict = field(default_factory=dict)       # the same statement as values, for code that checks it

    def public(self) -> dict:
        return {"text": self.text, "kind": self.kind, "version": self.version, "clause": self.clause,
                "source": self.passage.source if self.passage else None,
                "chunk_id": self.passage.chunk_id if self.passage else None, "data": self.data}


@dataclass
class GraphAnswer:
    question: str
    facts: list[Fact] = field(default_factory=list)
    passages: list[Hit] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    recognised: dict = field(default_factory=dict)

    def facts_text(self) -> str:
        """The facts as the lines of a prompt: [F1] ..., [F2] ..."""
        return "\n".join(f"[F{i}] {f.text}" for i, f in enumerate(self.facts, start=1))


def stem(word: str) -> str:
    """Plural and -ing/-ed endings off, so that "duplicates" meets "duplicate" and "splitting" meets "split"."""
    for ending in ("ing", "ed", "es", "s", "e"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            word = word[: -len(ending)]
            break
    return word[:-1] if len(word) > 4 and word[-1] == word[-2] else word


def merge_passages(linked: list[Hit], retrieved: list[Hit], k: int) -> list[Hit]:
    """What Ask AI is given: the passages the graph's facts cite first, then the retrieved ones not among them;
    at least ``k`` in all, and two retrieved ones beyond the graph's when it found any."""
    rest = [h for h in retrieved if all(h.chunk_id != p.chunk_id for p in linked)]
    return (linked + rest)[: max(k, len(linked) + 2)] if linked else retrieved[:k]


def parse_amounts(text: str) -> list[float]:
    """Amounts of money a question names: ₹30 lakh, Rs 7,50,000, 1.2 crore, 95,000 rupees, 2500000.

    A bare number counts as an amount only with four digits or more, so that rule numbers, versions and
    small counts are not read as money.
    """
    cleaned = CLAUSE_ID.sub(" ", VERSION.sub(lambda m: " " if m.group(0).lower().startswith("v") else m.group(0), text))
    out = []
    for m in AMOUNT.finditer(cleaned):
        digits = m.group("num").replace(",", "")
        unit = (m.group("unit") or "").lower()
        currency = m.group("cur") or m.group("cur2")
        if not (unit or currency or len(digits.split(".")[0]) >= 4):
            continue
        if not (unit or currency) and "," not in m.group("num") and 1990 <= float(digits) <= 2100:
            continue                              # a year, not money
        if unit == "l" and not currency:          # "3 l" alone is too ambiguous to be money
            continue
        try:
            value = float(digits) * UNITS.get(unit, 1)
        except ValueError:
            continue
        if value > 0:
            out.append(value)
    return out


def rupees(value: float) -> str:
    """₹ with Indian grouping: 3000000 -> ₹30,00,000."""
    whole = int(round(value))
    text = str(whole)
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        text = ",".join(groups + [tail])
    return f"₹{text}"


def control_functions() -> dict[str, str]:
    """The control function that checks each control clause, read from the code of ``controls.CONTROLS``."""
    found = {}
    for fn in controls.CONTROLS:
        named = set(re.findall(r'"(\d+\.\d+\.\d+)"', inspect.getsource(fn)))
        if len(named) == 1:                       # a control names exactly the rule it checks
            found[named.pop()] = fn.__name__
    return found


def checker_of(clause_id: str, kind: str, functions: dict[str, str]) -> tuple[str, str]:
    """(node name, description) of what checks a clause: a control function, or the agent whose remit covers it."""
    if kind == "control":
        name = functions.get(clause_id)
        return (f"control:{name}", f"{name}() in controls.py") if name else ("control:none", "no control function")
    for spec in AGENTS.values():
        if clause_id.startswith(spec.sections):
            return f"agent:{spec.name}", f"the {spec.title}"
    return "agent:none", "no agent"


class PolicyGraph:
    """The graph of one policy version (``version``), with what the other stored versions change."""

    def __init__(self, version: str, versions: list[dict], clauses: dict[str, dict], params: dict[str, dict],
                 passages: list[Hit], findings: dict[str, int] | None = None):
        self.version = version
        self.versions = versions                      # every stored version, oldest first
        self.clauses = clauses                        # version -> clause id -> {title, severity, kind}
        self.params = params                          # version -> clause id -> {name: value}
        self.passages = passages
        self.findings = findings or {}
        self.functions = control_functions()
        self.sections = {}
        for hit in passages:
            key = hit.section.split(" ", 1)[0].rstrip(".")
            if re.fullmatch(r"\d+(\.\d+)*", key) and key not in self.sections:
                self.sections[key] = hit.section.split(" ", 1)[1] if " " in hit.section else hit.section
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._build()

    # ------------------------------------------------------------------ building
    @classmethod
    def from_db(cls, conn: db.Database, version: str | None = None) -> "PolicyGraph":
        versions = [dict(r) for r in conn.execute(
            "SELECT version, policy_name, effective_date, is_active FROM company_policies")]
        versions.sort(key=lambda v: (str(v["effective_date"] or ""), [int(x) for x in re.findall(r"\d+", v["version"])]))
        if version is None:
            version = next((v["version"] for v in versions if v["is_active"]), versions[-1]["version"] if versions else None)
        if version is None or version not in {v["version"] for v in versions}:
            raise ValueError(f"no policy version {version!r} is stored")
        clauses: dict[str, dict] = {}
        for v, cid, title, severity, kind in conn.execute(
                "SELECT version, clause_id, title, severity, kind FROM policy_clauses ORDER BY version, clause_id"):
            clauses.setdefault(v, {})[cid] = {"title": title, "severity": severity, "kind": kind}
        params: dict[str, dict] = {}
        for v, cid, name, value in conn.execute(
                "SELECT version, clause_id, param_name, param_value FROM policy_parameters"):
            params.setdefault(v, {}).setdefault(cid, {})[name] = json.loads(value) if isinstance(value, str) else value
        passages = [Hit(r["chunk_id"], r["file_name"], r["version"], r["kind"], r["clause_id"], r["section"], r["page"],
                         r["text"], 1.0, 0) for r in conn.execute(
            "SELECT c.chunk_id, c.version, c.kind, c.clause_id, c.section, c.page, c.text, d.file_name "
            "FROM policy_chunks c JOIN policy_documents d ON d.doc_id = c.doc_id ORDER BY d.doc_id, c.position")]
        findings = {clause: int(n) for clause, n in conn.execute(
            "SELECT f.clause, COUNT(*) FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
            "WHERE f.status = 'kept' AND l.policy_version = ? GROUP BY f.clause", (version,))}
        return cls(version, versions, clauses, params, passages, findings)

    def passage(self, version: str, clause: str | None = None, section: str | None = None,
                containing: str | None = None) -> Hit | None:
        """The passage of a rule (or of a section's text, optionally the one containing a phrase) in a version."""
        for hit in self.passages:
            if hit.version != version:
                continue
            if clause and hit.clause_id == clause:
                return hit
            if section and hit.clause_id is None and hit.section.startswith(section + " ") and \
                    (containing is None or containing.lower() in hit.text.lower()):
                return hit
        return None

    def limits(self, version: str | None = None) -> tuple[str | None, dict[str, float]]:
        """The clause that holds the approval limits, and the limit of each role, lowest first."""
        for clause, values in self.params.get(version or self.version, {}).items():
            if isinstance(values.get("approval_limits"), dict):
                pairs = sorted(values["approval_limits"].items(), key=lambda kv: kv[1])
                return clause, {role: float(limit) for role, limit in pairs}
        return None, {}

    def _node(self, node_id: str, kind: str, label: str, **attrs) -> None:
        self.nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label, **attrs})

    def _edge(self, source: str, target: str, kind: str, label: str = "") -> None:
        self.edges.append({"source": source, "target": target, "kind": kind, "label": label})

    def _page(self, hit: Hit | None) -> str | None:
        if hit is None:
            return None
        node = f"page:{hit.document}:{hit.page}"
        self._node(node, "page", f"{hit.document} p.{hit.page}", document=hit.document, page=hit.page)
        return node

    def _build(self) -> None:
        v = self.version
        root = f"version:{v}"
        meta = next(x for x in self.versions if x["version"] == v)
        self._node(root, "version", f"v{v}", active=bool(meta["is_active"]), effective=str(meta["effective_date"] or ""))
        limit_clause, limits = self.limits(v)
        for cid, c in sorted(self.clauses.get(v, {}).items(), key=lambda kv: [int(x) for x in kv[0].split(".")]):
            section = cid.rsplit(".", 1)[0]
            snode = f"section:{section}"
            if snode not in self.nodes:
                self._node(snode, "section", f"{section} {self.sections.get(section, '')}".strip())
                self._edge(root, snode, "has section")
            cnode = f"clause:{cid}"
            self._node(cnode, "clause", cid, title=c["title"], severity=c["severity"], clause_kind=c["kind"],
                       findings=self.findings.get(cid, 0))
            self._edge(snode, cnode, "has rule")
            checker, description = checker_of(cid, c["kind"], self.functions)
            self._node(checker, "checker", description, checker_kind="agent" if checker.startswith("agent:") else "control")
            self._edge(cnode, checker, "checked by")
            page = self._page(self.passage(v, clause=cid))
            if page:
                self._edge(cnode, page, "stated on")
            for name, value in self.params.get(v, {}).get(cid, {}).items():
                pnode = f"param:{cid}:{name}"
                self._node(pnode, "parameter", name, value=value, clause=cid)
                self._edge(cnode, pnode, "sets")
        if limit_clause:
            pnode = f"param:{limit_clause}:approval_limits"
            page = self._page(self.passage(v, section=limit_clause.rsplit(".", 1)[0], containing="limit"))
            if page:
                self._edge(pnode, page, "stated on")
            for role, limit in limits.items():
                rnode = f"role:{role}"
                self._node(rnode, "role", role, limit=limit)
                self._edge(pnode, rnode, "limit", rupees(limit))
        for other in self.versions:
            if other["version"] == v:
                continue
            onode = f"version:{other['version']}"
            self._node(onode, "version", f"v{other['version']}", active=bool(other["is_active"]),
                       effective=str(other["effective_date"] or ""), other=True)
            for change in self.changes(v, other["version"]):
                target = f"param:{change['clause']}:{change['parameter']}" if change["parameter"] else f"clause:{change['clause']}"
                if target in self.nodes:
                    self._edge(onode, target, "changes", f"{change['from']} -> {change['to']}")

    # ------------------------------------------------------------------ reading
    def changes(self, a: str, b: str) -> list[dict]:
        """What version ``b`` changes from version ``a``: parameters (per role for the approval limits), and
        rules added, removed or given another severity or kind."""
        out = []
        ca, cb = self.clauses.get(a, {}), self.clauses.get(b, {})
        for cid in sorted(set(ca) | set(cb), key=lambda k: [int(x) for x in k.split(".")]):
            if cid not in cb or cid not in ca:
                out.append({"clause": cid, "parameter": None, "role": None, "from": "present" if cid in ca else "absent",
                            "to": "present" if cid in cb else "absent"})
                continue
            for key in ("severity", "kind"):
                if ca[cid][key] != cb[cid][key]:
                    out.append({"clause": cid, "parameter": None, "role": None, "from": ca[cid][key], "to": cb[cid][key]})
            pa, pb = self.params.get(a, {}).get(cid, {}), self.params.get(b, {}).get(cid, {})
            for name in sorted(set(pa) | set(pb)):
                x, y = pa.get(name), pb.get(name)
                if x == y:
                    continue
                if isinstance(x, dict) and isinstance(y, dict):
                    for role in sorted(set(x) | set(y)):
                        if x.get(role) != y.get(role):
                            out.append({"clause": cid, "parameter": name, "role": role, "from": x.get(role), "to": y.get(role)})
                else:
                    out.append({"clause": cid, "parameter": name, "role": None, "from": x, "to": y})
        return out

    def public(self) -> dict:
        kinds = {}
        for n in self.nodes.values():
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        return {"version": self.version,
                "versions": [{**v, "effective_date": str(v["effective_date"] or ""), "is_active": bool(v["is_active"])}
                             for v in self.versions],
                "nodes": list(self.nodes.values()), "edges": self.edges, "counts": kinds}

    # ------------------------------------------------------------------ questions
    def recognise(self, question: str, index: PolicyIndex | None = None) -> dict:
        """What a question names: rules, versions, roles, amounts, checkers, severities, kinds, topics."""
        text = question
        clauses = [c for c in CLAUSE_ID.findall(text) if c in self.clauses.get(self.version, {})]
        stored = {v["version"] for v in self.versions}
        versions = list(dict.fromkeys(v for v in VERSION.findall(text) if v in stored))
        _, limits = self.limits()
        lowered = text.lower()
        roles = []
        for synonym, role in ROLE_SYNONYMS.items():
            if synonym in lowered and role in limits:
                roles.append(role)
        rest = lowered
        for role in sorted(limits, key=len, reverse=True):                     # "senior manager" before "manager"
            if re.search(rf"\b{re.escape(role.lower())}s?\b", rest):
                roles.append(role)
                rest = re.sub(rf"\b{re.escape(role.lower())}s?\b", " ", rest)
        agents = []
        for name, spec in AGENTS.items():
            words = spec.title.lower().replace(" agent", "").split(" and ")
            phrases = {" and ".join(words), " & ".join(words), " ".join(words), name.replace("_", " "), f"{words[0]} agent"}
            if any(re.search(rf"\b{re.escape(ph)}\b", lowered) for ph in phrases):
                agents.append(name)
        severities = [m.group(1).lower() for pattern in SEVERITY_WORDS for m in pattern.finditer(text)]
        kinds = []
        if SET_INTENT.search(text):
            if JUDGEMENT_WORDS.search(text) and not agents:
                kinds.append("judgement")
            if CONTROL_WORDS.search(text):
                kinds.append("control")
        words = {stem(w) for w in re.findall(r"[a-z]+", lowered) if len(w) > 3}
        titles = {cid: {stem(w) for w in re.findall(r"[a-z]+", c["title"].lower()) if len(w) > 3}
                  for cid, c in self.clauses.get(self.version, {}).items()}
        frequency: dict[str, int] = {}
        for title in titles.values():
            for w in title:
                frequency[w] = frequency.get(w, 0) + 1
        topics = [cid for cid, title in titles.items()
                  if title and (title <= words or any(w in words and w not in GENERIC and frequency[w] <= 3 for w in title))]
        amounts = parse_amounts(text)
        if index is not None and not (clauses or topics or amounts or roles or versions or agents or severities or kinds):
            for hit in index.search(question, k=2, mode="lexical"):    # nothing named: the topic, by wording
                if hit.clause_id and hit.clause_id in self.clauses.get(self.version, {}):
                    topics.append(hit.clause_id)
        return {"clauses": clauses, "versions": versions, "roles": list(dict.fromkeys(roles)),
                "amounts": amounts, "agents": agents, "severities": list(dict.fromkeys(severities)),
                "kinds": list(dict.fromkeys(kinds)), "topics": list(dict.fromkeys(t for t in topics if t not in clauses)),
                "change": bool(CHANGE_WORDS.search(text))}

    def query(self, question: str, index: PolicyIndex | None = None, max_passages: int = 6) -> GraphAnswer:
        """The facts of the graph that bear on a question, with their passages and the nodes they come from."""
        v = self.version
        seen = self.recognise(question, index)
        out = GraphAnswer(question, recognised=seen)
        rules = self.clauses.get(v, {})
        limit_clause, limits = self.limits()
        focus: list[str] = list(seen["clauses"])

        def add(fact: Fact, *nodes: str) -> None:
            if all(f.text != fact.text for f in out.facts):
                out.facts.append(fact)
            out.nodes.extend(n for n in nodes if n in self.nodes and n not in out.nodes)

        # Amounts: the role that may approve each, the structuring band, round amounts.
        band_clause, band = self._param("guide_band_pct")
        round_clause, multiple = self._param("round_amount_multiple")
        limits_passage = self.passage(v, section=limit_clause.rsplit(".", 1)[0], containing="limit") if limit_clause else None
        for amount in seen["amounts"]:
            if not limits:
                break
            focus.append(limit_clause)
            allowed = [r for r, limit in limits.items() if amount <= limit]
            if allowed:
                lowest = allowed[0]
                text = (f"Under v{v}, {rupees(amount)} is within the approval limit of a {lowest} ({rupees(limits[lowest])}); "
                        f"the lowest role that may approve it is {lowest}")
                below = [r for r in limits if r not in allowed]
                if below:
                    text += f", and a {' or '.join(below)} may not (rule {limit_clause})"
                add(Fact(text + ".", "routing", v, limit_clause, limits_passage,
                         {"amount": amount, "lowest": lowest}), f"role:{lowest}",
                    f"param:{limit_clause}:approval_limits", f"clause:{limit_clause}")
            else:
                top = list(limits)[-1]
                add(Fact(f"Under v{v}, {rupees(amount)} is above every approval limit (the highest is the {top}'s, "
                         f"{rupees(limits[top])}): whoever approves it breaks rule {limit_clause}.", "routing", v,
                         limit_clause, limits_passage, {"amount": amount, "lowest": None}), f"role:{top}",
                    f"clause:{limit_clause}")
            for role in seen["roles"]:
                verdict = "may" if amount <= limits[role] else "may not"
                add(Fact(f"Under v{v}, a {role} (limit {rupees(limits[role])}) {verdict} approve {rupees(amount)} "
                         f"(rule {limit_clause}).", "routing", v, limit_clause, limits_passage,
                         {"amount": amount, "role": role, "allowed": amount <= limits[role]}),
                    f"role:{role}", f"clause:{limit_clause}")
            if band_clause and band:
                for role, limit in limits.items():
                    if limit * (1 - band / 100) <= amount <= limit:
                        focus.append(band_clause)
                        add(Fact(f"{rupees(amount)} is within {band:g}% under the {role} limit ({rupees(limit)}), the band "
                                 f"rule {band_clause} names as a guide to structuring: invoices just below a limit that "
                                 f"together exceed it.", "band", v, band_clause, self.passage(v, clause=band_clause),
                                 {"amount": amount, "role": role, "clause": band_clause}),
                            f"clause:{band_clause}", f"param:{band_clause}:guide_band_pct", f"role:{role}")
            if round_clause and multiple and amount % multiple == 0:
                focus.append(round_clause)
                add(Fact(f"{rupees(amount)} is an exact multiple of {rupees(multiple)}: rule {round_clause} "
                         f"({rules[round_clause]['title'].lower()}, {rules[round_clause]['severity']}) applies.", "round", v,
                         round_clause, self.passage(v, clause=round_clause), {"amount": amount, "clause": round_clause}),
                    f"clause:{round_clause}")

        # Roles named without an amount: their limits.
        if seen["roles"] and not seen["amounts"] and limit_clause:
            focus.append(limit_clause)
            for role in seen["roles"]:
                add(Fact(f"Under v{v}, a {role} may approve invoices up to {rupees(limits[role])} (rule {limit_clause}).",
                         "limit", v, limit_clause, limits_passage, {"role": role, "limit": limits[role]}),
                    f"role:{role}", f"param:{limit_clause}:approval_limits")

        # Versions: what changed, between the versions named or between this one and the others.
        if seen["change"] or len(seen["versions"]) >= 2:
            named = seen["versions"]
            if len(named) >= 2:
                pairs = [(named[i], named[i + 1]) for i in range(len(named) - 1)]
            elif named and named[0] != v:
                pairs = [(v, named[0])]
            else:
                pairs = [(v, x["version"]) for x in self.versions if x["version"] != v]
            restrict = set(seen["clauses"] + seen["topics"]) | ({limit_clause} if seen["roles"] else set())
            for a, b in pairs:
                a, b = self._ordered(a, b)
                found = self.changes(a, b)
                for cid in sorted(c for c in restrict if c in rules and all(ch["clause"] != c for ch in found)):
                    focus.append(cid)
                    add(Fact(f"From v{a} to v{b}, rule {cid} ({self._title(cid)}) does not change.", "change", b, cid,
                             self.passage(b, clause=cid), {"clause": cid, "unchanged": True, "from_version": a}),
                        f"clause:{cid}", f"version:{a}", f"version:{b}")
                    old = self.passage(a, clause=cid)
                    if old and all(p.chunk_id != old.chunk_id for p in out.passages):
                        out.passages.append(old)
                for ch in found:
                    if restrict and ch["clause"] not in restrict:
                        continue
                    focus.append(ch["clause"])
                    what = (f"the {ch['role']} limit" if ch["role"] else
                            f"{ch['parameter']}" if ch["parameter"] else "the rule")
                    text = (f"From v{a} to v{b}, rule {ch['clause']} ({self._title(ch['clause'])}) changes {what} from "
                            f"{self._show(ch['from'], ch['parameter'])} to {self._show(ch['to'], ch['parameter'])}.")
                    add(Fact(text, "change", b, ch["clause"], self._change_passage(b, ch), {**ch, "from_version": a}),
                        f"clause:{ch['clause']}", f"version:{a}", f"version:{b}",
                        f"param:{ch['clause']}:{ch['parameter']}" if ch["parameter"] else "", f"role:{ch['role']}" if ch["role"] else "")
                    old = self._change_passage(a, ch)
                    if old and all(p.chunk_id != old.chunk_id for p in out.passages):
                        out.passages.append(old)
                if not any(f.kind == "change" and f.version == b for f in out.facts) and not restrict:
                    add(Fact(f"v{b} changes no rule of v{a}.", "change", b), f"version:{a}", f"version:{b}")

        # Sets: rules of a severity or kind; the remit of an agent.
        for severity in seen["severities"]:
            members = [c for c, x in rules.items() if x["severity"] == severity]
            add(Fact(f"The {severity} rules of v{v} are {self._list(members)}.", "set", v,
                     data={"severity": severity, "members": members}), *(f"clause:{c}" for c in members))
            focus.extend(members)
        for kind in seen["kinds"]:
            members = [c for c, x in rules.items() if x["kind"] == kind]
            how = "judged by the agents" if kind == "judgement" else "checked by code"
            add(Fact(f"The {kind} rules of v{v}, {how}, are {self._list(members)}.", "set", v,
                     data={"kind": kind, "members": members}), *(f"clause:{c}" for c in members))
            focus.extend(members)
        for name in seen["agents"]:
            spec = AGENTS[name]
            members = [c for c, x in rules.items() if x["kind"] == "judgement" and c.startswith(spec.sections)]
            add(Fact(f"The {spec.title} reads sections {', '.join(s.rstrip('.') for s in spec.sections)} and judges "
                     f"{self._list(members) if members else 'no rule'} of v{v}.", "checker", v,
                     data={"agent": f"agent:{name}", "members": members}), f"agent:{name}",
                *(f"clause:{c}" for c in members))
            focus.extend(members)

        # Every rule in focus: what it is, what checks it, what it sets.
        for cid in dict.fromkeys(c for c in focus + seen["topics"] if c in rules):
            c = rules[cid]
            checker, description = checker_of(cid, c["kind"], self.functions)
            hit = self.passage(v, clause=cid)
            add(Fact(f"Rule {cid} ({c['title'].lower()}) is {c['severity']}, a {c['kind']} rule "
                     f"{'checked by ' + description if c['kind'] == 'control' else 'judged by ' + description}.",
                     "rule", v, cid, hit, {"clause": cid, "checker": checker, "severity": c["severity"], "kind": c["kind"]}),
                f"clause:{cid}", checker, f"section:{cid.rsplit('.', 1)[0]}", self._page_id(hit))
            for name, value in self.params.get(v, {}).get(cid, {}).items():
                if name == "approval_limits":
                    continue
                add(Fact(f"Rule {cid} sets {name} = {self._show(value, name)} in v{v}.", "parameter", v, cid, hit,
                         {"clause": cid, "name": name, "value": value}),
                    f"param:{cid}:{name}")
        out.nodes.insert(0, f"version:{v}")

        # Passages: those the facts cite, in order, then any older version's passages already gathered.
        cited = []
        for f in out.facts:
            if f.passage and all(p.chunk_id != f.passage.chunk_id for p in cited):
                cited.append(f.passage)
        out.passages = (cited + [p for p in out.passages if all(p.chunk_id != c.chunk_id for c in cited)])[:max_passages]
        return out

    # ------------------------------------------------------------------ helpers
    def _param(self, name: str) -> tuple[str | None, float | None]:
        for cid, values in self.params.get(self.version, {}).items():
            if name in values and isinstance(values[name], (int, float)):
                return cid, float(values[name])
        return None, None

    def _title(self, cid: str) -> str:
        for v in (self.version, *[x["version"] for x in self.versions]):
            if cid in self.clauses.get(v, {}):
                return self.clauses[v][cid]["title"].lower()
        return "unknown rule"

    def _ordered(self, a: str, b: str) -> tuple[str, str]:
        order = [x["version"] for x in self.versions]
        return (a, b) if order.index(a) <= order.index(b) else (b, a)

    def _change_passage(self, version: str, change: dict) -> Hit | None:
        if change["role"]:
            return self.passage(version, section=change["clause"].rsplit(".", 1)[0], containing="limit") or \
                self.passage(version, clause=change["clause"])
        return self.passage(version, clause=change["clause"])

    def _page_id(self, hit: Hit | None) -> str:
        return f"page:{hit.document}:{hit.page}" if hit else ""

    @staticmethod
    def _show(value, name: str | None) -> str:
        """A parameter's value as the policy states it: percentages, rupees, counts, lists."""
        if value is None:
            return "nothing"
        if isinstance(value, list):
            return ", ".join(str(x) for x in value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if name and name.endswith("_pct"):
                return f"{value:g}%"
            if name is None or "limit" in name or "multiple" in name:
                return rupees(value)
            return f"{value:g}"
        return str(value)

    @staticmethod
    def _list(members: list[str]) -> str:
        return ", ".join(members) if members else "none"
