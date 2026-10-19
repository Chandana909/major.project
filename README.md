# AuditIQ: major project

A controls-first, multi-agent audit of procure-to-pay transactions, with a REST
API and a web application whose views of vendor risk, the audit pipeline and
policy changes are drawn in 3D with React Three Fiber.

**Writing the paper? Start with [`RESULTS.md`](RESULTS.md):** every measured
result, with its table, figure, source file and the command that produced it.

**The full report, methodology, every result in detail and the analysis:**
[`REPORT.md`](REPORT.md) (https://github.com/Chandana909/major.project/blob/main/REPORT.md).

**Reading the results with a program or another language model?** Every
result is also in one JSON file,
[`auditiq/results/results.json`](auditiq/results/results.json)
(raw: https://raw.githubusercontent.com/Chandana909/major.project/main/auditiq/results/results.json),
with the kind of each number, the question it answers, its source files and
the command that produced it.

| Folder | Content |
|---|---|
| [`auditiq/`](auditiq/README.md) | The system, the web application (`auditiq/frontend/`), the AuditIQ-Bench datasets, the evaluation harness, results and documentation. Start with its README. |
| [`paper/`](paper/) | The paper (`auditiq_paper.tex`, `auditiq_paper.pdf`), the measured section on policy-driven controls (`policy_feature.tex`, `policy_feature.pdf`), a 6-page conference version with formal propositions (`paper/conference/main.tex`, `main.pdf`), and a project overview for the team (`AuditIQ_Project_Overview.pdf`, source in `paper/overview/`). |

Run every command from `auditiq/`. Quick start, with no model and no database
server (Python 3.11 or later; Node 20 or later for the web application):

```bash
cd auditiq
pip install -e ".[dev]"
python -m pytest
python -m auditiq setup --dataset data/large_seed_505
python -m auditiq run --config C1
cd frontend && npm ci && npm run build && cd ..
python -m auditiq serve
```

The web application is then at http://127.0.0.1:8000 and the API description
at http://127.0.0.1:8000/api/docs ([`auditiq/docs/WEB.md`](auditiq/docs/WEB.md)).

The measured feature and its results:
[`auditiq/docs/FEATURE_POLICY_AS_DATA.md`](auditiq/docs/FEATURE_POLICY_AS_DATA.md).
Every measured number and how to reproduce it: the "What has been measured"
section of [`auditiq/README.md`](auditiq/README.md).
