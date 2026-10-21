"""results/results.json, the machine-readable copy of every result, must match the files it is built from."""
from __future__ import annotations

import json

from auditiq.policy import PROJECT_ROOT
from evaluation import collect_results, full_report


def test_the_machine_readable_results_match_their_sources():
    stored = json.loads(collect_results.OUT.read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(collect_results.build())), "run: python -m evaluation.collect_results"


def test_the_full_report_is_up_to_date():
    assert full_report.OUT.read_text(encoding="utf-8") == full_report.render(), "run: python -m evaluation.full_report"


def test_every_source_of_a_result_is_in_the_repository_with_its_public_address():
    results = json.loads(collect_results.OUT.read_text(encoding="utf-8"))["results"]
    assert results, "no result"
    for name, entry in results.items():
        assert entry["label"] in ("measured", "pilot", "sample"), name
        assert entry["question"] and entry["command"].startswith("python -m "), name
        for src in entry["sources"]:
            assert (PROJECT_ROOT.parent / src["path"]).is_file(), src["path"]
            assert src["raw_url"] == collect_results.RAW + src["path"], src


def test_a_model_run_still_going_is_left_out_of_the_report(tmp_path):
    """Its files appear once its report does, so the report does not depend on a run in progress."""
    finished = full_report.finished
    run = tmp_path / "C3-igpu90.jsonl"
    run.write_text("", encoding="utf-8")
    assert not finished(run) and not finished(tmp_path / "C1-igpu90.meta.json")
    (tmp_path / "igpu90.md").write_text("", encoding="utf-8")
    assert finished(run) and finished(tmp_path / "C1-igpu90.meta.json")
    assert all(finished(tmp_path / name) for name in ("C0-IF.jsonl", "C0-SVM.jsonl", "C1.jsonl", "C1_v2.5.jsonl"))
