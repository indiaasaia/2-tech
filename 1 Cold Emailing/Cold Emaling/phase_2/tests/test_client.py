from contact_discovery.gemini_client import (
    GeminiClient,
    discover_with_fallback,
    is_retryable,
)


class _FakeAPIError(Exception):
    def __init__(self, code=None, status=None, status_code=None):
        self.code = code
        self.status = status
        self.status_code = status_code
        super().__init__(f"error {code} {status}")


def _recorded_call_model(results):
    """Builds a call_model that consults a {model: result-or-exc} map."""
    calls = []

    def call_model(model):
        calls.append(model)
        outcome = results[model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return call_model, calls


def test_is_retryable_codes():
    assert is_retryable(_FakeAPIError(code=429))       # rate limit
    assert is_retryable(_FakeAPIError(code=503))       # unavailable
    assert is_retryable(_FakeAPIError(code=529))       # overloaded
    assert not is_retryable(_FakeAPIError(code=400))   # bad request


def test_is_retryable_gaos_compat_error_shape():
    # The GAOS compat error hierarchy exposes status_code, not code.
    assert is_retryable(_FakeAPIError(code=None, status_code=429))
    assert is_retryable(_FakeAPIError(code=None, status_code=503))
    assert not is_retryable(_FakeAPIError(code=None, status_code=400))


def test_is_retryable_statuses():
    assert is_retryable(_FakeAPIError(code=200, status="RESOURCE_EXHAUSTED"))
    assert is_retryable(_FakeAPIError(code=None, status="RATE_LIMIT_EXCEEDED"))
    assert not is_retryable(_FakeAPIError(code=200, status="INVALID_ARGUMENT"))


def test_falls_back_to_next_model_on_rate_limit():
    results = {
        "primary": _FakeAPIError(code=429),
        "fallback": "HR Team | hr@company.com",
    }
    call_model, calls = _recorded_call_model(results)
    out = discover_with_fallback(call_model, ["primary", "fallback"], 0.2)
    assert out == "HR Team | hr@company.com"
    assert calls == ["primary", "fallback"]


def test_fails_fast_on_hard_error():
    results = {
        "primary": _FakeAPIError(code=400),
        "fallback": "should not be reached",
    }
    call_model, calls = _recorded_call_model(results)
    try:
        discover_with_fallback(call_model, ["primary", "fallback"], 0.2)
    except _FakeAPIError:
        pass
    else:
        raise AssertionError("expected hard error to propagate")
    assert calls == ["primary"]  # fallback never tried


def test_raises_last_error_when_all_models_exhausted():
    results = {
        "a": _FakeAPIError(code=429, status="RESOURCE_EXHAUSTED"),
        "b": _FakeAPIError(code=503),
    }
    call_model, calls = _recorded_call_model(results)
    try:
        discover_with_fallback(call_model, ["a", "b"], 0.2)
    except _FakeAPIError as exc:
        assert exc.code == 503  # last error surfaces
    else:
        raise AssertionError("expected exhaustion to raise")
    assert calls == ["a", "b"]


def test_gemini_client_uses_chain_and_tracks_last_model(monkeypatch):
    client = GeminiClient(api_key="dummy-key", model="primary", fallback_models=("fallback",))
    served = []

    def fake_call(model, system_instruction, user_content, temperature):
        served.append(model)
        if model == "primary":
            raise _FakeAPIError(code=429)
        return "CTO | cto@company.com"

    monkeypatch.setattr(client, "_call", fake_call)
    out = client.discover("sys", "user", temperature=0.1)
    assert out == "CTO | cto@company.com"
    assert served == ["primary", "fallback"]
    assert client.last_model == "fallback"


def test_gemini_client_fails_fast_on_hard_error(monkeypatch):
    client = GeminiClient(api_key="dummy-key", model="primary", fallback_models=("fallback",))
    served = []

    def fake_call(model, system_instruction, user_content, temperature):
        served.append(model)
        raise _FakeAPIError(code=403)

    monkeypatch.setattr(client, "_call", fake_call)
    try:
        client.discover("sys", "user")
    except _FakeAPIError:
        pass
    else:
        raise AssertionError("expected 403 to propagate")
    assert served == ["primary"]
    assert client.last_model is None
