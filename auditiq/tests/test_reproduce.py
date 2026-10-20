"""The comparison of scripts/reproduce.py: dates, the machine and durations may differ between runs; nothing
else may."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reproduce.py"
spec = importlib.util.spec_from_file_location("reproduce", SCRIPT)
reproduce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reproduce)


def test_a_changed_count_is_a_difference_and_a_changed_timing_is_not():
    table = "| Ledger | Findings | Audit (s) |\n|---|---|---|\n| bench_seed_101 | 300 | 10.6 |"
    assert reproduce.compare_text(table, table.replace("10.6", "24.6"))[0] == []
    assert reproduce.compare_text(table, table.replace("300", "301"))[0] != []
    sentence = "Produced by `x` on 2026-10-18 14:06. Adopting took 0.03 s; 12 findings."
    assert reproduce.compare_text(sentence, sentence.replace("2026-10-18 14:06", "2026-10-20 09:00")
                                  .replace("0.03 s", "0.04 s"))[0] == []
    assert reproduce.compare_text(sentence, sentence.replace("12 findings", "13 findings"))[0] != []


def test_volatile_keys_of_a_json_result_are_ignored_and_values_are_not():
    a = {"produced": "2026-10-18 14:06", "machine": "laptop", "audit_seconds": 96.0,
         "variants": [{"name": "Strict policy", "affected": 12274, "frozen": {"exact": 27726}}]}
    b = {**a, "produced": "2026-10-20 09:00", "audit_seconds": 101.5}
    diffs, ignored = reproduce.compare_json(a, b)
    assert diffs == [] and sorted(ignored) == [".audit_seconds", ".produced"]
    c = {**a, "variants": [{"name": "Strict policy", "affected": 12275, "frozen": {"exact": 27726}}]}
    assert reproduce.compare_json(a, c)[0] == [".variants[0].affected: 12274 against 12275"]


def test_every_step_writes_outside_the_working_copy(tmp_path):
    for name, commands in reproduce.steps(tmp_path).items():
        for command in commands:
            outputs = [command[i + 1] for i, arg in enumerate(command) if arg in ("--out", "--pdfs", "--store")]
            assert all(Path(o).is_relative_to(tmp_path) for o in outputs), name
            assert outputs or name == "manifests", name      # verifying the manifests only reads
