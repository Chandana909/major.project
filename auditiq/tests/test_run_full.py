"""The command for the full LLM run (evaluation.run_full), end to end against a stand-in endpoint.

The stand-in answers every request with "no finding", so these tests check the command: the environment, the
model client over HTTP, the subprocesses, the prediction files and the report. They say nothing about a model.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evaluation import run_full


class StandIn(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):  # noqa: N802 (the name is set by http.server)
        length = int(self.headers.get("Content-Length", 0))
        json.loads(self.rfile.read(length) or b"{}")
        StandIn.calls += 1
        reply = {"choices": [{"index": 0, "message": {"role": "assistant", "content": '{"flags": []}'},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 5}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture()
def endpoint(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    StandIn.calls = 0
    monkeypatch.setenv("AUDITIQ_LLM_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1")
    monkeypatch.setenv("AUDITIQ_LLM_MODEL", "stand-in")
    yield StandIn
    server.shutdown()


def test_the_full_run_command_audits_each_configuration_and_writes_the_comparison(endpoint, small_dataset, tmp_path):
    argv = ["--ledgers", small_dataset.name, "--data", str(small_dataset.parent), "--results", str(tmp_path),
            "--configs", "C1", "C3", "C2", "--n", "8", "--workers", "2", "--no-cache"]
    assert run_full.main(argv) == 0

    folder = tmp_path / small_dataset.name
    counts = {c: len((folder / f"{c}-full.jsonl").read_text(encoding="utf-8").splitlines()) for c in ("C1", "C3", "C2")}
    assert len(set(counts.values())) == 1 and counts["C1"] >= 8      # the same invoices for every configuration
    n = counts["C1"]
    assert endpoint.calls == 3 * n + n                                 # three agents per invoice (C3), one prompt (C2)
    meta = json.loads((folder / "C3-full.meta.json").read_text(encoding="utf-8"))
    assert meta["model"] == "stand-in" and meta["summary"]["llm_calls"] == 3 * n
    report = (folder / "full.md").read_text(encoding="utf-8")
    assert report.startswith(f"# Sample of the evaluation subset on `{small_dataset.name}`")
    assert "Model: stand-in." in report and "C3-full vs C2-full" in report

    # the report alone is written again from the same files
    assert run_full.main([*argv, "--report-only"]) == 0
    assert (folder / "full.md").read_text(encoding="utf-8") == report


def test_the_full_run_refuses_changed_prompts(endpoint, small_dataset, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_full, "frozen_prompt_hash", lambda: "0000000000000000")
    argv = ["--ledgers", small_dataset.name, "--data", str(small_dataset.parent), "--results", str(tmp_path),
            "--configs", "C3", "--n", "4", "--no-cache"]
    assert run_full.main(argv) == 2
    assert "the prompts changed" in capsys.readouterr().err
    assert endpoint.calls == 0 and not (tmp_path / small_dataset.name).exists()


def test_the_full_run_needs_a_model(small_dataset, tmp_path, capsys):
    argv = ["--ledgers", small_dataset.name, "--data", str(small_dataset.parent), "--results", str(tmp_path),
            "--configs", "C3"]
    assert run_full.main(argv) == 2
    assert "No model is configured" in capsys.readouterr().err


def test_a_full_run_report_is_taken_into_the_results_and_the_report(tmp_path, monkeypatch):
    from evaluation import collect_results, full_report

    sample = (collect_results.RESULTS / "bench_seed_101" / "sample34.md").read_text(encoding="utf-8")
    (tmp_path / "bench_seed_101").mkdir()
    (tmp_path / "bench_seed_101" / "full.md").write_text(
        "# Full run on `bench_seed_101`\n" + sample.split("\n", 1)[1], encoding="utf-8")
    monkeypatch.setattr(collect_results, "RESULTS", tmp_path)
    monkeypatch.setattr(full_report, "RESULTS", tmp_path)

    entry = collect_results.full_runs()["llm_stages_full_run_bench_seed_101"]
    assert entry["label"] == "measured" and entry["command"] == "python -m evaluation.run_full --ledgers bench_seed_101"
    assert entry["metrics"]["Model findings naming a violated rule"]["C3"]["value"] == 0.375
    section = "\n".join(full_report.full_run_section())
    assert "#### Full run on `bench_seed_101`" in section and "Not run yet" not in section
    assert "| C3-sample34 vs C2-sample34 |" in section      # the McNemar tests of the report
