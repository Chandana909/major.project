"""Tests of the model client. No test makes a network call."""
from __future__ import annotations

import json

import httpx
import pytest

from auditiq.llm import LLMError, LLMSettings, OpenAIChatClient, ResponseCache, ScriptedClient, extract_json

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def server(replies: list, seen: list):
    """A fake endpoint that answers with ``replies`` in order and records the requests."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = replies[min(len(seen) - 1, len(replies) - 1)]
        if isinstance(reply, tuple):
            status, headers = reply
            return httpx.Response(status, headers=headers, text="busy")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}],
                                         "usage": {"prompt_tokens": 11, "completion_tokens": 7}})
    return httpx.MockTransport(handler)


def client(replies, seen, cache=None, **settings) -> OpenAIChatClient:
    base = dict(base_url="http://test/v1", model="m-1", max_retries=2)
    return OpenAIChatClient(LLMSettings(**{**base, **settings}), cache, transport=server(replies, seen),
                            sleep=lambda _: None)


@pytest.mark.parametrize("text, expected", [
    ('{"flags": []}', {"flags": []}),
    ('```json\n{"flags": [{"clause": "2.1.4"}]}\n```', {"flags": [{"clause": "2.1.4"}]}),
    ('<think>the rule says {x}</think>\n{"flags": []}', {"flags": []}),
    ('Here is the result: {"verdicts": [{"id": 1, "verdict": "keep"}]} Hope it helps.',
     {"verdicts": [{"id": 1, "verdict": "keep"}]}),
    ('{broken {"flags": []}', {"flags": []}),
])
def test_extract_json_tolerates_fences_reasoning_and_prose(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "no exception found", "[1, 2, 3]", "{not json}", None])
def test_extract_json_rejects_a_reply_without_an_object(text):
    with pytest.raises(ValueError):
        extract_json(text)


def test_request_body_and_reply():
    seen = []
    reply = client(['{"flags": []}'], seen, api_key="k-123").complete(MESSAGES, temperature=0.7, sample=3)
    body = json.loads(seen[0].content)
    assert seen[0].url == "http://test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer k-123"
    assert body == {"model": "m-1", "messages": MESSAGES, "temperature": 0.7, "max_tokens": 700,
                    "response_format": {"type": "json_object"}, "seed": 3}
    assert (reply.text, reply.prompt_tokens, reply.completion_tokens, reply.cached) == ('{"flags": []}', 11, 7, False)


def test_optional_request_fields_can_be_switched_off():
    seen = []
    client(["{}"], seen, json_mode=False, send_seed=False, extra_body={"top_p": 1}).complete(MESSAGES)
    body = json.loads(seen[0].content)
    assert "response_format" not in body and "seed" not in body and body["top_p"] == 1
    assert "authorization" not in seen[0].headers


def test_cache_returns_the_stored_reply_and_separates_samples(tmp_path):
    seen, cache = [], ResponseCache(tmp_path / "cache.sqlite")
    c = client(["first", "second", "third"], seen, cache)
    assert c.complete(MESSAGES).text == "first"
    again = c.complete(MESSAGES)
    assert (again.text, again.cached, again.prompt_tokens) == ("first", True, 11) and len(seen) == 1
    assert c.complete(MESSAGES, temperature=0.7, sample=1).text == "second"       # a different request
    assert c.complete(MESSAGES, temperature=0.7, sample=2).text == "third"        # a different sample
    assert c.complete(MESSAGES, temperature=0.7, sample=1).text == "second" and len(seen) == 3
    cache.close()
    # The cache survives the process.
    reopened = ResponseCache(tmp_path / "cache.sqlite")
    assert client(["never used"], [], reopened).complete(MESSAGES).text == "first"
    reopened.close()


def test_samples_stay_distinct_in_the_cache_even_when_no_seed_is_sent(tmp_path):
    seen, cache = [], ResponseCache(tmp_path / "cache.sqlite")
    c = client(["a", "b"], seen, cache, send_seed=False)
    assert [c.complete(MESSAGES, temperature=0.7, sample=k).text for k in (1, 2, 1)] == ["a", "b", "a"]
    cache.close()


def test_rate_limit_is_retried_and_a_bad_request_is_not():
    seen = []
    assert client([(429, {"retry-after": "1"}), (503, {}), "ok"], seen).complete(MESSAGES).text == "ok"
    assert len(seen) == 3

    seen = []
    with pytest.raises(LLMError, match="failed after 3 attempts"):
        client([(500, {})], seen).complete(MESSAGES)
    assert len(seen) == 3

    seen = []
    with pytest.raises(LLMError, match="rejected the request"):
        client([(400, {})], seen).complete(MESSAGES)
    assert len(seen) == 1


def test_a_prompt_that_would_not_fit_the_context_is_refused_before_it_is_sent():
    seen = []
    c = client(["ok"], seen, context_tokens=1000, max_tokens=700)
    assert c.complete([{"role": "user", "content": "x" * 600}]).text == "ok"          # 222 + 700 tokens
    with pytest.raises(LLMError, match="more than the context of 1000 tokens"):
        c.complete([{"role": "user", "content": "x" * 1200}])                          # 444 + 700 tokens
    assert len(seen) == 1
    client(["ok"], seen).complete([{"role": "user", "content": "x" * 100000}])         # no limit configured


def test_settings_come_from_the_environment(monkeypatch):
    for name in ("AUDITIQ_LLM_BASE_URL", "AUDITIQ_LLM_MODEL", "AUDITIQ_LLM_API_KEY", "AUDITIQ_LLM_JSON_MODE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="No model is configured"):
        LLMSettings.from_env(env_file=None)
    monkeypatch.setenv("AUDITIQ_LLM_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("AUDITIQ_LLM_MODEL", "some-model:7b")
    monkeypatch.setenv("AUDITIQ_LLM_JSON_MODE", "0")
    settings = LLMSettings.from_env(env_file=None)
    assert (settings.base_url, settings.model, settings.json_mode, settings.api_key) == \
        ("http://localhost:11434/v1", "some-model:7b", False, "")


def test_scripted_client_records_its_calls():
    c = ScriptedClient(lambda messages, temperature, sample: f"{temperature}-{sample}")
    assert c.complete(MESSAGES, temperature=0.7, sample=2).text == "0.7-2"
    assert c.calls == [{"messages": MESSAGES, "temperature": 0.7, "sample": 2}]
