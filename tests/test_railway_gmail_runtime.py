from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "gmail_runtime.py"
SPEC = spec_from_file_location("railway_gmail_runtime_test", MODULE_PATH)
assert SPEC and SPEC.loader
runtime = module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class Config:
    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.missing = missing


class Ingress:
    ensure_calls = 0

    def __init__(self, _store: object, _config: Config) -> None:
        self._config = _config

    def ensure_watch(self) -> dict[str, object]:
        type(self).ensure_calls += 1
        return {"status": "healthy", "renewed": True}

    def health(self) -> dict[str, object]:
        return {"watch": {"status": "healthy", "history_id": "private", "observability": {"parser_error_count": 0}}}


def test_configured_runtime_returns_ingress_and_redacted_health():
    Ingress.ensure_calls = 0
    ingress, health = runtime.configure_gmail_ingress(
        {"GMAIL_STATE_PATH": "state.sqlite3"},
        config_factory=lambda _env: Config(),
        store_factory=lambda path: {"path": path},
        ingress_factory=Ingress,
    )
    assert isinstance(ingress, Ingress)
    assert Ingress.ensure_calls == 1
    assert health == {
        "status": "ready",
        "watch_status": "healthy",
        "observability": {"parser_error_count": 0},
        "error": None,
    }


def test_missing_configuration_is_visible_without_private_values():
    ingress, health = runtime.configure_gmail_ingress(
        {},
        config_factory=lambda _env: Config(("GMAIL_WATCH_TOPIC",)),
        store_factory=lambda _path: object(),
        ingress_factory=Ingress,
    )
    assert isinstance(ingress, Ingress)
    assert health["status"] == "configuration_missing"
    assert health["error"] is None


def test_factory_failure_is_explicit_and_fail_closed():
    ingress, health = runtime.configure_gmail_ingress(
        {},
        config_factory=lambda _env: (_ for _ in ()).throw(RuntimeError("boom")),
        store_factory=lambda _path: object(),
        ingress_factory=Ingress,
    )
    assert ingress is None
    assert health == {
        "status": "failed",
        "watch_status": "not_checked",
        "observability": {},
        "error": "RuntimeError",
    }
