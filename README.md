# AuditIQ: major project

A controls-first, multi-agent audit of procure-to-pay transactions.

| Folder | Content |
|---|---|
| [`auditiq/`](auditiq/README.md) | The system, the AuditIQ-Bench datasets, the evaluation harness, results and documentation. Start with its README. |
| [`paper/`](paper/) | The paper draft (`auditiq_paper.tex`) and the measured section on policy-driven controls (`policy_feature.tex`, `policy_feature.pdf`). |

Run every command from `auditiq/`. Quick start, with no model and no database server:

```bash
cd auditiq
pip install -e ".[dev]"
python -m pytest
python -m auditiq setup --dataset data/large_seed_505
python -m auditiq run --config C1
python -m streamlit run app/dashboard.py
```

The measured feature and its results: [`auditiq/docs/FEATURE_POLICY_AS_DATA.md`](auditiq/docs/FEATURE_POLICY_AS_DATA.md).
