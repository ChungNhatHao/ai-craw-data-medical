from app.utils.logging import build_secret_filter, redact_text


def test_redact_text_replaces_all_configured_secrets() -> None:
    secrets = frozenset({"private-user", "private-password"})

    result = redact_text(
        "login private-user failed with private-password",
        secrets,
    )

    assert result == "login [REDACTED] failed with [REDACTED]"


def test_log_filter_redacts_message_and_sensitive_extra() -> None:
    record = {
        "message": "failed for private-user",
        "extra": {
            "username": "private-user",
            "password": "private-password",
        },
    }

    assert build_secret_filter(frozenset({"private-user", "private-password"}))(record)
    assert record["message"] == "failed for [REDACTED]"
    assert record["extra"] == {
        "username": "[REDACTED]",
        "password": "[REDACTED]",
    }

