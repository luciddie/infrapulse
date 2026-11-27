from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ALERTMANAGER_DIR = (
    ROOT / "monitoring" / "alertmanager"
)

BASE_CONFIG = ALERTMANAGER_DIR / "alertmanager.yml"

TELEGRAM_CONFIG = (
    ALERTMANAGER_DIR / "alertmanager.telegram.yml"
)

BASE_COMPOSE = ROOT / "compose.yml"

TELEGRAM_COMPOSE = ROOT / "compose.telegram.yml"

PROMETHEUS_CONFIG = (
    ROOT
    / "monitoring"
    / "prometheus"
    / "prometheus.yml"
)

GITIGNORE = ROOT / ".gitignore"


def read_file(path):
    return path.read_text(encoding="utf-8-sig")


def test_base_config_exists():
    assert BASE_CONFIG.is_file()


def test_telegram_config_exists():
    assert TELEGRAM_CONFIG.is_file()


def test_base_config_has_no_telegram_credentials():
    config = read_file(BASE_CONFIG)

    assert "bot_token" not in config
    assert "chat_id" not in config
    assert "telegram_configs" not in config


def test_telegram_uses_secret_files():
    config = read_file(TELEGRAM_CONFIG)

    assert (
        "bot_token_file: /run/secrets/telegram_bot_token"
        in config
    )

    assert (
        "chat_id_file: /run/secrets/telegram_chat_id"
        in config
    )


def test_resolved_notifications_enabled():
    config = read_file(TELEGRAM_CONFIG)

    assert "send_resolved: true" in config


def test_inhibition_configured():
    for path in (BASE_CONFIG, TELEGRAM_CONFIG):
        config = read_file(path)

        assert "inhibit_rules:" in config
        assert "source_matchers:" in config
        assert "target_matchers:" in config


def test_base_compose_without_telegram_secrets():
    compose = read_file(BASE_COMPOSE)

    assert "telegram_bot_token" not in compose
    assert "telegram_chat_id" not in compose


def test_telegram_compose_exists():
    assert TELEGRAM_COMPOSE.is_file()


def test_telegram_compose_secret_paths():
    compose = read_file(TELEGRAM_COMPOSE)

    assert "./secrets/telegram_bot_token" in compose
    assert "./secrets/telegram_chat_id" in compose
    assert "alertmanager.telegram.yml" in compose


def test_alertmanager_version_pinned():
    compose = read_file(BASE_COMPOSE)

    assert "prom/alertmanager:v0.35.1" in compose


def test_prometheus_alertmanager_integration():
    config = read_file(PROMETHEUS_CONFIG)

    assert "alerting:" in config
    assert "alertmanagers:" in config
    assert "alertmanager:9093" in config


def test_secrets_gitignored():
    rules = read_file(GITIGNORE).splitlines()

    assert "/secrets/" in rules
