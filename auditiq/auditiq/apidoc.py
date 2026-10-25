"""The reference of the REST API, written from the application itself.

    python -m auditiq.apidoc            writes docs/API.md

Every endpoint of `auditiq/api.py` with its method and path, what it does (its docstring), whether it needs
the token, its parameters and request body with their types and limits, and the answers it can give. The
parameters come from the Python signatures and the request models, the answers from the code of each
endpoint, so the file cannot drift from the code: a test checks that it is current. The guide to the API
(jobs, errors, examples of use from the web application) is docs/WEB.md, Section 4.
"""
from __future__ import annotations

import inspect
import re
import types
import typing
from pathlib import Path

from fastapi.params import Depends as DependsParam
from fastapi.params import File as FileParam
from fastapi.params import Form as FormParam
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.requests import Request

from . import api

DOC = Path(__file__).resolve().parents[1] / "docs" / "API.md"

ANSWERS = {
    200: "the answer, as JSON",
    202: "a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`",
    400: "the request was refused; `detail` says why",
    401: "the server requires a token, and the request has none or a wrong one",
    403: "the token's user does not have the role the endpoint needs",
    404: "no such record",
    409: "the request conflicts with the state of the server; `detail` says with what",
    413: "the upload is too large",
    415: "the upload is not of the expected type",
    422: "the parameters or the body are not valid, or the document cannot be executed; `detail` lists why",
    503: "the database cannot be reached",
}
TAG_TITLES = {"status": "Status", "review": "Review", "policy": "Policy", "ledger": "Ledger",
              "copilot": "Copilot", "jobs": "Jobs", "results": "Results"}


def type_name(annotation) -> str:
    """A type as a reader of the API sees it."""
    if annotation is inspect.Parameter.empty or annotation is typing.Any:
        return "any"
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Literal:
        return " or ".join(f"`{a}`" for a in args)
    if origin in (typing.Union, types.UnionType):
        names = [type_name(a) for a in args if a is not type(None)]
        return " or ".join(names) + (" or null" if type(None) in args else "")
    if origin in (list, tuple, set):
        return f"list of {type_name(args[0])}" if args else "list"
    if origin is dict or annotation is dict:
        return "object"
    simple = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in simple:
        return simple[annotation]
    if inspect.isclass(annotation) and annotation.__name__ == "UploadFile":
        return "file"
    return getattr(annotation, "__name__", str(annotation))


def limits(field) -> str:
    """The constraints pydantic enforces on a field, as text."""
    out = []
    for item in getattr(field, "metadata", []):
        for name, label in (("min_length", "at least {} characters"), ("max_length", "at most {} characters"),
                            ("ge", "at least {}"), ("le", "at most {}")):
            value = getattr(item, name, None)
            if value is not None:
                out.append(label.format(value))
    if field.description:                  # a shape such as {"<rule>": ...} is code; as text, GitHub hides <rule>
        out.append(f"`{field.description}`" if "<" in field.description else field.description)
    return "; ".join(out)


def default_text(value) -> str:
    if value is inspect.Parameter.empty:
        return "required"
    if value == "" or value is None:
        return "empty" if value == "" else "null"
    return f"`{str(value).lower() if isinstance(value, bool) else value}`"


def endpoint(route: APIRoute) -> dict:
    hints = typing.get_type_hints(route.endpoint, include_extras=False)
    signature = inspect.signature(route.endpoint)
    source = inspect.getsource(route.endpoint)
    path_names = set(re.findall(r"{(\w+)}", route.path))
    params, body, form = [], None, []
    uses_store = False
    for name, p in signature.parameters.items():
        annotation = hints.get(name, p.annotation)
        if isinstance(p.default, DependsParam):
            uses_store = True
            continue
        if annotation is Request:
            continue
        if isinstance(p.default, (FileParam, FormParam)):
            default = p.default.default
            form.append({"name": name, "type": type_name(annotation),
                         "default": "required" if default is ... else default_text(default)})
            continue
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            body = annotation
            continue
        params.append({"name": name, "in": "path" if name in path_names else "query", "type": type_name(annotation),
                       "default": "required" if name in path_names else default_text(p.default)})
    role = next((d.dependency.required_role for d in route.dependencies
                 if hasattr(d.dependency, "required_role")), None)
    protected = role is not None
    codes = {route.status_code or 200}
    codes |= {int(c) for c in re.findall(r"HTTPException\(\s*(\d{3})", source)}
    kinds = re.findall(r'jobs\.start\("([\w-]+)"', source)
    if any(api.CONFLICTS.get(k) for k in kinds):
        codes.add(409)
    if protected:
        codes |= {401, 503}                  # the role is read from the store
    if role in ("reviewer", "admin"):
        codes.add(403)
    if params or body or form:
        codes.add(422)
    if uses_store:
        codes.add(503)
    return {"method": ", ".join(sorted(route.methods)), "path": route.path, "tag": (route.tags or ["other"])[0],
            "doc": " ".join((inspect.getdoc(route.endpoint) or "").split()), "protected": protected, "role": role,
            "params": params, "body": body, "form": form, "codes": sorted(codes), "jobs": kinds}


def endpoints() -> list[dict]:
    app = api.create_app(target="unused.db", token="", cors_origins=[])
    return [endpoint(r) for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")]


def render() -> str:
    found = endpoints()
    out = ["# REST API reference", "",
           f"All {len(found)} endpoints of the AuditIQ API (`auditiq/api.py`, served by `python -m auditiq serve`). "
           "**This file is generated** from the application by `python -m auditiq.apidoc`; a test checks that it "
           "is current. How to use the API (jobs, errors, the token, how the web application calls it) is in "
           "[`WEB.md`](WEB.md), Section 4; the interactive version of this reference is at `/api/docs` on a "
           "running server.", "",
           "**Common to every endpoint.** Requests and answers are JSON, except the two uploads (multipart). An "
           "error answer carries `detail`: a message, or `{\"message\", \"problems\"}`. When the server has users "
           "(`python -m auditiq user add`) or a shared token (`AUDITIQ_API_TOKEN`), every endpoint but the open ones "
           "needs the header `Authorization: Bearer <token>`, and the token's role must be at least the one listed: "
           "a `viewer` reads, a `reviewer` also records decisions and audits invoices again, an `admin` also changes "
           "the policy and the ledger. The shared token acts as an admin; a server with neither is open. "
           "Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and "
           "`Referrer-Policy: no-referrer`.", "",
           "**Background jobs.** An endpoint that answers 202 has started a job; `GET /api/jobs/{id}` reports it. "
           "Jobs that would change the ledger under one another are refused with 409 while the other runs: "
           + "; ".join(f"`{kind}` waits for {', '.join(f'`{c}`' for c in sorted(conflicts))}"
                       for kind, conflicts in api.CONFLICTS.items()) + ".", "",
           "| Method | Path | Role | Answers |", "|---|---|---|---|"]
    out += [f"| {e['method']} | [`{e['path']}`](#{anchor(e)}) | {e['role'] or 'open'} | "
            f"{', '.join(map(str, e['codes']))} |" for e in found]
    out.append("")
    for tag in dict.fromkeys(e["tag"] for e in found):
        out += [f"## {TAG_TITLES.get(tag, tag.title())}", ""]
        for e in (e for e in found if e["tag"] == tag):
            out += [f"### {e['method']} `{e['path']}`", "", e["doc"] or "(no description)", "",
                    (f"Role: at least `{e['role']}` when the server has users or a token." if e["protected"]
                     else "Role: none; open to everyone.")
                    + (f" Starts a background job of kind `{e['jobs'][0]}`." if e["jobs"] else ""), ""]
            if e["params"]:
                out += ["| Parameter | In | Type | Default |", "|---|---|---|---|"]
                out += [f"| `{p['name']}` | {p['in']} | {p['type']} | {p['default']} |" for p in e["params"]]
                out.append("")
            if e["form"]:
                out += ["Multipart form:", "", "| Field | Type | Default |", "|---|---|---|"]
                out += [f"| `{f['name']}` | {f['type']} | {f['default']} |" for f in e["form"]]
                out.append("")
            if e["body"] is not None:
                out += [f"JSON body (`{e['body'].__name__}`):", "", "| Field | Type | Default | Limits |",
                        "|---|---|---|---|"]
                for name, field in e["body"].model_fields.items():
                    if field.is_required():
                        default = "required"
                    elif field.default_factory is not None:
                        default = "empty"
                    else:
                        default = default_text(field.default)
                    out.append(f"| `{name}` | {type_name(field.annotation)} | {default} | {limits(field)} |")
                out.append("")
            out += ["Answers:", ""] + [f"- **{c}**: {ANSWERS.get(c, '')}" for c in e["codes"]] + [""]
    return "\n".join(out)


def anchor(e: dict) -> str:
    """The GitHub anchor of an endpoint's heading."""
    heading = f"{e['method']} {e['path']}".lower()
    return re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")


def main() -> None:
    DOC.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
