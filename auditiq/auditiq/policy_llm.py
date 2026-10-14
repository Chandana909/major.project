"""Reading a policy that is not written in the template's wording.

    python -m auditiq policy adopt company_policy.pdf --llm
    python -m auditiq policy adopt company_policy.pdf --llm --accept-verified --reviewer "A. Auditor"

`policy_extract` reads thresholds by pattern, which works only for documents in
the wording of the SOP template. An organisation's own policy states the same
rules in its own words. Here a language model does the reading, and three
things keep its output from being trusted blindly:

1. The model proposes. For each rule the system executes, it returns the
   sentences of the document that state the rule, copied word for word, and the
   values of the rule's parameters.
2. Code verifies. A quote must occur in the document; a value must be stated
   in a verified quote of its rule (as digits, with separators, or as a number
   word); a value must be of the right kind. Anything else is marked for
   attention with the reason.
3. A person confirms. Nothing is stored until a named reviewer accepts the
   verified values and supplies or corrects the others.

The verification catches a value the document does not state where the model
says it does. It cannot catch a quote that is real but belongs to another rule;
that is what the person is for.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import db, policy_ingest
from .llm import ChatClient, extract_json
from .policy import WEEK, Policy

# What each rule says, without any number: the model must take numbers from the document.
RULES = {
    "2.1.1": "the invoice amount must equal the purchase-order amount, within a tolerance",
    "2.1.2": "the quantity billed must not exceed the quantity received",
    "2.1.3": "an invoice must refer to a purchase order and a goods receipt that exist",
    "2.1.4": "remarks on a goods receipt about rejected, damaged or returned goods reduce the accepted quantity",
    "2.1.5": "the goods or services described on the invoice must be those that were ordered",
    "2.2.1": "an invoice number already used by the same vendor is a duplicate",
    "2.2.2": "an invoice that repeats an earlier one under a re-typed or altered invoice number is a duplicate",
    "3.1.1": "the GSTIN must have a fixed number of alphanumeric characters",
    "3.1.2": "the first two characters of the GSTIN must be a state code within a range",
    "3.1.3": "the GSTIN on the invoice must be the vendor's registered GSTIN",
    "4.1.1": "a vendor may have only a limited number of invoices dated on the same day",
    "4.1.2": "several invoices just below an approval limit within a short period are one divided purchase",
    "4.2.1": "an invoice dated on a non-business day is an exception",
    "4.3.1": "an invoice amount that is an exact multiple of a round amount is an exception",
    "4.4.1": "an invoice from a blacklisted vendor, or from one whose GST registration has a blocking status, is an exception",
    "5.1.1": "an invoice amount above the approval limit of the role that approved it is an exception",
}
PARAMETERS = {
    ("2.1.1", "amount_tolerance_pct"): "the tolerance in percent of the purchase-order amount (a number)",
    ("3.1.1", "gstin_length"): "the required number of characters (an integer)",
    ("3.1.2", "state_code_min"): "the lowest valid state code (an integer)",
    ("3.1.2", "state_code_max"): "the highest valid state code (an integer)",
    ("4.1.1", "max_invoices_per_vendor_per_day"): "the largest number of invoices one vendor may have on one day (an integer)",
    ("4.1.2", "guide_window_days"): "the length of the period in days (an integer)",
    ("4.1.2", "guide_band_pct"): "how close to the approval limit, in percent of the limit (a number)",
    ("4.2.1", "non_business_days"): "the days of the week that are not business days (a list of English day names)",
    ("4.3.1", "round_amount_multiple"): "the round amount in rupees (an integer)",
    ("4.4.1", "blocked_gstin_statuses"): "the registration statuses that block a vendor (a list of words)",
    ("5.1.1", "approval_limits"): "the approval limit in rupees of each approver role (an object: role name to integer)",
}
SYSTEM = """You read an organisation's procurement policy and locate rules and their thresholds in it.
You never invent text. Every quote you give must be copied character for character from the document.
You never guess a number. A value you give must be written in one of your quotes for that rule.
Reply with one JSON object and nothing else."""
TASK = """Below is a list of rules, then a policy document.

For every rule of the list that the document states, give:
- "clause": the identifier of the rule from the list;
- "quotes": one to three short passages of the document that state the rule, each copied word for word (the sentence or the table row that contains the rule or its threshold; at most 40 words each);
- "values": the value of each parameter listed for the rule, as the document states it. Amounts in rupees as plain integers (1 lakh is 100000, 1 crore is 10000000).

Leave out a rule that the document does not state. Do not add rules that are not in the list.

Reply in this form:
{"version": "<version number the document states, or null>",
 "rules": [{"clause": "<identifier>", "quotes": ["<passage>"], "values": {"<parameter>": <value>}}]}

RULES
<<rules>>

POLICY DOCUMENT
<<document>>"""
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
VERIFIED, ATTENTION, MISSING = "verified", "needs attention", "missing"


@dataclass
class Proposal:
    """What the model proposed for one document, after verification by code."""
    file: str
    title: str
    version: str | None
    pages: int
    model: str
    text: str                                              # the document, page by page
    rules: dict[str, dict] = field(default_factory=dict)   # clause -> {"located": bool, "quotes": [(text, page)]}
    items: list[dict] = field(default_factory=list)        # one per parameter: value, status, reason, quote, page
    problems: list[str] = field(default_factory=list)      # what stops the adoption as proposed
    usage: dict = field(default_factory=dict)              # tokens and seconds of the model call

    def item(self, clause: str, name: str) -> dict:
        return next(i for i in self.items if (i["clause"], i["parameter"]) == (clause, name))


def normalize(text: str) -> str:
    """Whitespace collapsed and typographic quotes and dashes made plain, for comparing a quote with the document."""
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-", " ": " "}))
    return re.sub(r"\s+", " ", text).strip().casefold()


def document_pages(path: Path) -> tuple[list[str], str]:
    """The text of each page, and the document's title."""
    lines, pages, title = policy_ingest.read_lines(Path(path))
    text = [" ".join(line["text"].strip() for line in lines
                     if line["page"] == number and not policy_ingest.FOOTER.search(line["text"]))
            for number in range(1, pages + 1)]
    return text, title or Path(path).stem


def indian(n: int) -> str:
    """12500000 -> '1,25,00,000'."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


def number_forms(value) -> set[str]:
    """Ways a document may write a number: 100000, 100,000, 1,00,000, 1 lakh; 3, three; 0.5, .5."""
    x = float(value)
    if not x.is_integer():
        s = repr(x)
        return {s, s.lstrip("0")}
    n = int(x)
    forms = {str(n), f"{n:,}", indian(n), f"{n:02d}"}
    if 2 <= n <= 20:                       # "one" is too common a word to count as the number 1
        forms.add(WORDS[n])
    if n >= 100000 and n % 100000 == 0:
        forms |= {f"{n // 100000} lakh", f"{n // 100000} lakhs"}
    if n >= 10000000 and n % 10000000 == 0:
        forms |= {f"{n // 10000000} crore", f"{n // 10000000} crores"}
    return forms


def states(text: str, form: str) -> bool:
    """Does the (normalized) text contain this form as a whole number or word, not as part of a longer one?"""
    return re.search(rf"(?<![\w.,]){re.escape(form.casefold())}(?![\w]|[.,]\d)", text) is not None


def stated(value, quotes: str) -> bool:
    """Is the value written in the quoted text?"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return any(states(quotes, form) for form in number_forms(value))
    if isinstance(value, str):
        return value.casefold() in quotes
    if isinstance(value, list):
        return bool(value) and all(stated(v, quotes) for v in value)
    if isinstance(value, dict):
        return bool(value) and all(str(k).casefold() in quotes and stated(v, quotes) for k, v in value.items())
    return False


def coerce(clause: str, name: str, value, reference):
    """The value in the form the registry uses, or a ValueError that says what is wrong with it."""
    if isinstance(reference, dict):
        if not isinstance(value, dict) or not value:
            raise ValueError("expected a limit for each role")
        known = {role.casefold(): role for role in reference}
        out = {}
        for role, limit in value.items():
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 0:
                raise ValueError(f"the limit of {role} is not a positive amount")
            out[known.get(str(role).strip().casefold(), str(role).strip())] = int(limit) if float(limit).is_integer() else float(limit)
        missing = [role for role in reference if role not in out]
        if missing:
            raise ValueError(f"no limit for {', '.join(missing)}")
        return out
    if isinstance(reference, list):
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
            raise ValueError("expected a list of words")
        items = [v.strip().title() for v in value]
        if name == "non_business_days":
            items = [day.rstrip("s") if day.rstrip("s") in WEEK else day for day in items]
            wrong = [day for day in items if day not in WEEK]
            if wrong:
                raise ValueError(f"'{wrong[0]}' is not a day of the week")
        return items
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")
    if value < 0 or (name.endswith("_pct") and value > 100):
        raise ValueError("out of range")
    if isinstance(reference, int):
        if not float(value).is_integer():
            raise ValueError("expected a whole number")
        return int(value)
    return float(value)


def messages(pages: list[str], reference: dict) -> list[dict]:
    lines = []
    for clause, spec in reference["clauses"].items():
        params = [f"{name}: {PARAMETERS[(clause, name)]}" for name in spec["params"]]
        lines.append(f"- {clause}: {RULES[clause]}." + (" Parameters: " + "; ".join(params) + "." if params else " No parameter."))
    document = "\n\n".join(f"[page {number}]\n{text}" for number, text in enumerate(pages, start=1))
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": TASK.replace("<<rules>>", "\n".join(lines)).replace("<<document>>", document)}]


def verify(reply: dict, pages: list[str], reference: dict) -> tuple[dict, list[dict], list[str]]:
    """Check a model's reply against the document. Returns (rules, items, problems)."""
    plain = [normalize(page) for page in pages]
    proposed = {}
    for entry in reply.get("rules") or []:
        if isinstance(entry, dict) and str(entry.get("clause")) in reference["clauses"]:
            proposed.setdefault(str(entry["clause"]), entry)
    rules, items, problems = {}, [], []
    for clause, spec in reference["clauses"].items():
        entry = proposed.get(clause, {})
        quotes = []
        for quote in entry.get("quotes") or []:
            if not isinstance(quote, str) or len(normalize(quote)) < 8:
                continue
            page = next((number for number, text in enumerate(plain, start=1) if normalize(quote) in text), None)
            if page is not None:
                quotes.append((quote.strip(), page))
        rules[clause] = {"located": bool(quotes), "quotes": quotes}
        if not quotes:
            problems.append(f"Rule {clause} ({spec['title'].lower()}): no passage of the document was located for it")
        quoted = " ".join(normalize(q) for q, _ in quotes)
        values = entry.get("values") if isinstance(entry.get("values"), dict) else {}
        for name, old in spec["params"].items():
            item = {"clause": clause, "parameter": name, "reference": old, "value": None, "status": MISSING,
                    "reason": "the model gave no value", "quote": quotes[0][0] if quotes else "",
                    "page": quotes[0][1] if quotes else None}
            if name in values and values[name] is not None:
                try:
                    item["value"] = coerce(clause, name, values[name], old)
                except ValueError as error:
                    item.update(status=ATTENTION, reason=str(error), value=values[name])
                else:
                    if not quotes:
                        item.update(status=ATTENTION, reason="no quote of the rule was found in the document")
                    elif stated(item["value"], quoted):
                        item.update(status=VERIFIED, reason="")
                    else:
                        item.update(status=ATTENTION, reason="the value is not written in the quoted text")
            items.append(item)
    return rules, items, problems


def propose(path: Path, reference: dict, client: ChatClient) -> Proposal:
    """Let the model read a policy document, and verify what it returns against the document."""
    pages, title = document_pages(Path(path))
    reply = client.complete(messages(pages, reference), temperature=0.0)
    out = Proposal(file=Path(path).name, title=title, version=None, pages=len(pages),
                   model=getattr(client, "model", "unknown"), text="\n\n".join(pages))
    out.usage = {"prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
                 "seconds": round(reply.latency_ms / 1000, 1), "from_cache": bool(getattr(reply, "cached", False))}
    try:
        data = extract_json(reply.text)
    except ValueError:
        out.problems.append("the model's reply could not be read")
        data = {}
    version = policy_ingest.VERSION.search(out.text) or re.search(r"[Vv]ersion\s*:?\s*(\d+(?:\.\d+)*)", out.text)
    out.version = version.group(1) if version else None        # from the document itself, not from the model
    out.rules, out.items, problems = verify(data, pages, reference)
    out.problems += problems
    return out


def add_passages(proposal: Proposal, passages: dict[str, str]) -> list[str]:
    """Passages the person supplies for rules the model did not locate.

    Each passage must occur in the document, like a quote of the model. The
    rule then counts as located, and the model's values for it are checked
    against the person's passage. Returns the rules whose passage was not found
    in the document.
    """
    plain = [normalize(page) for page in proposal.text.split("\n\n")]
    not_found = []
    for clause, passage in passages.items():
        page = next((number for number, text in enumerate(plain, start=1) if normalize(passage) in text), None)
        if clause not in proposal.rules or page is None or len(normalize(passage)) < 8:
            not_found.append(clause)
            continue
        proposal.rules[clause] = {"located": True, "quotes": [(passage.strip(), page)], "by_person": True}
        proposal.problems = [p for p in proposal.problems if not p.startswith(f"Rule {clause} ")]
        for item in proposal.items:
            if item["clause"] != clause or item["value"] is None or item["status"] == VERIFIED:
                continue
            item.update(quote=passage.strip(), page=page)
            if item["reason"] == "no quote of the rule was found in the document":
                verified = stated(item["value"], normalize(passage))
                item.update(status=VERIFIED if verified else ATTENTION,
                            reason="" if verified else "the value is not written in the quoted text")
    return not_found


def decide(proposal: Proposal, accept_verified: bool = False, overrides: dict | None = None) -> tuple[dict, list[str]]:
    """The values that will be stored, and what is still open.

    ``accept_verified`` is the person's acceptance of every value that code
    verified. ``overrides`` are values the person supplies:
    ``{(clause, parameter): value}``. Returns ``({clause: {parameter: value}}, open)``.
    """
    overrides = overrides or {}
    values: dict[str, dict] = {}
    still_open = []
    for item in proposal.items:
        key = (item["clause"], item["parameter"])
        if key in overrides:
            values.setdefault(key[0], {})[key[1]] = coerce(*key, overrides[key], item["reference"])
        elif item["status"] == VERIFIED and accept_verified:
            values.setdefault(key[0], {})[key[1]] = item["value"]
        elif item["status"] == VERIFIED:
            still_open.append(f"Rule {key[0]} {key[1]} = {json.dumps(item['value'])}: verified, waiting for confirmation")
        else:
            still_open.append(f"Rule {key[0]} {key[1]}: {item['reason']}; supply the value")
    return values, still_open


def adopt(conn: db.Database, path: Path, proposal: Proposal, reference: dict, values: dict, reviewer: str,
          version: str | None = None, activate: bool = False, replace: bool = False) -> dict:
    """Store a confirmed proposal as a policy version, with the located passages for citation."""
    version = version or proposal.version
    problems = list(proposal.problems)
    if not reviewer.strip():
        problems.append("a policy read by a model is adopted only with the name of the person who confirmed it")
    if not version:
        problems.append("the document states no version; give one")
    lacking = [f"{clause}.{name}" for clause, spec in reference["clauses"].items() for name in spec["params"]
               if name not in values.get(clause, {})]
    if lacking:
        problems.append("no confirmed value for " + ", ".join(lacking))
    report = {"file": proposal.file, "version": version, "adopted": False, "problems": problems}
    if problems:
        return report
    if conn.scalar("SELECT 1 FROM company_policies WHERE version = ?", (version,)) and not replace:
        report["problems"].append(f"version {version} is already stored; give another version number, or pass replace")
        return report

    supplied = sorted(f"{i['clause']}.{i['parameter']}" for i in proposal.items
                      if i["status"] != VERIFIED or values[i["clause"]][i["parameter"]] != i["value"])
    supplied += sorted(f"passage of {clause}" for clause, rule in proposal.rules.items() if rule.get("by_person"))
    registry = {
        "policy_name": proposal.title, "version": version, "effective_date": None,
        "clauses": {clause: {"title": spec["title"], "severity": spec["severity"], "kind": spec["kind"],
                             "params": values.get(clause, {})} for clause, spec in reference["clauses"].items()},
        # How this version came to be: a record for whoever audits the audit.
        "adoption": {"method": "proposed by a model, verified against the document by code, confirmed by a person",
                     "model": proposal.model, "confirmed_by": reviewer.strip(), "confirmed_at": db.now(),
                     "values_supplied_by_the_person": supplied, "reference_version": reference["version"]},
    }
    db.store_policy(conn, Policy(registry, proposal.text), active=False)
    conn.execute("DELETE FROM policy_documents WHERE file_name = ?", (proposal.file,))
    doc_id = conn.insert(
        "INSERT INTO policy_documents (file_name, title, version, pages, sha256, ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
        (proposal.file, proposal.title, version, proposal.pages, hashlib.sha256(Path(path).read_bytes()).hexdigest(),
         db.now()), "doc_id")
    chunks = [("clause", clause, f"Rule {clause}", rule["quotes"][0][1], " ... ".join(q for q, _ in rule["quotes"]))
              for clause, rule in proposal.rules.items()]
    chunks += [("text", None, f"Page {number}", number, text)
               for number, text in enumerate(proposal.text.split("\n\n"), start=1) if text.strip()]
    conn.executemany(
        "INSERT INTO policy_chunks (doc_id, version, position, kind, clause_id, section, page, text, verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        [(doc_id, version, position, *chunk) for position, chunk in enumerate(chunks)])
    if activate:
        db.set_active_policy(conn, version, commit=False)
    conn.commit()
    report.update(adopted=True, rules=len(registry["clauses"]), active=activate, values_supplied_by_the_person=supplied)
    return report
