"""results/results.json, the machine-readable copy of every result, must match the files it is built from."""
from __future__ import annotations

import json

from auditiq.policy import PROJECT_ROOT
from evaluation import collect_results


def test_the_machine_readable_results_match_their_sources():
    stored = json.loads(collect_results.OUT.read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(collect_results.build())), "run: python -m evaluation.collect_results"


def test_every_source_of_a_result_is_in_the_repository_with_its_public_address():
    results = json.loads(collect_results.OUT.read_text(encoding="utf-8"))["results"]
    assert results, "no result"
    for name, entry in results.items():
        assert entry["label"] in ("measured", "pilot", "sample"), name
        assert entry["question"] and entry["command"].startswith("python -m "), name
        for src in entry["sources"]:
            assert (PROJECT_ROOT.parent / src["path"]).is_file(), src["path"]
            assert src["raw_url"] == collect_results.RAW + src["path"], src
