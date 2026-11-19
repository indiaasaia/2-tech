from contact_discovery.config import Config


def test_defaults():
    config = Config()
    assert config.model == "gemini-3.7-flash"
    assert config.fallback_models == ("gemini-3.6-flash", "gemini-3.5-flash")
    assert config.max_iterations == 3
    assert config.limit is None


def test_from_env_full(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite, gemini-3.5-flash-lite")
    monkeypatch.setenv("CONTACT_TEMPERATURE", "0.1")
    monkeypatch.setenv("CONTACT_MAX_ITERATIONS", "5")
    monkeypatch.setenv("CONTACT_LIMIT", "7")
    monkeypatch.setenv("CONTACT_CSV", "out/contacts.csv")

    config = Config.from_env()
    assert config.api_key == "AIza-test"
    assert config.model == "gemini-3.5-flash"
    assert config.fallback_models == ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite")
    assert config.temperature == 0.1
    assert config.max_iterations == 5
    assert config.limit == 7
    assert config.csv_path == "out/contacts.csv"


def test_from_env_ignores_unset_optional(monkeypatch):
    monkeypatch.delenv("CONTACT_LIMIT", raising=False)
    config = Config.from_env()
    assert config.limit is None


def test_from_env_ignores_empty_optional(monkeypatch):
    monkeypatch.setenv("CONTACT_LIMIT", "")
    config = Config.from_env()
    assert config.limit is None


def test_with_overrides_ignores_none():
    config = Config(max_iterations=5)
    updated = config.with_overrides(max_iterations=None, limit=2)
    assert updated.max_iterations == 5  # None ignored
    assert updated.limit == 2
