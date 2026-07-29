from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_compose_forwards_stage16_configuration_to_backend() -> None:
    compose_text = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    required = {
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT_SECONDS",
        "MAIL_FROM_NAME",
        "EMAIL_CODE_TTL_SECONDS",
        "EMAIL_CODE_RESEND_SECONDS",
        "EMAIL_CODE_MAX_ATTEMPTS",
        "CHAT_INPUT_PRICE_PER_MILLION_TOKENS_CNY",
        "CHAT_OUTPUT_PRICE_PER_MILLION_TOKENS_CNY",
    }

    assert all(f"{name}:" in compose_text for name in required)


def test_deployment_example_documents_stage16_configuration() -> None:
    env_example = (PROJECT_ROOT / "deploy" / ".env.example").read_text(
        encoding="utf-8"
    )
    required = {
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT_SECONDS",
        "MAIL_FROM_NAME",
        "EMAIL_CODE_TTL_SECONDS",
        "EMAIL_CODE_RESEND_SECONDS",
        "EMAIL_CODE_MAX_ATTEMPTS",
        "CHAT_INPUT_PRICE_PER_MILLION_TOKENS_CNY",
        "CHAT_OUTPUT_PRICE_PER_MILLION_TOKENS_CNY",
    }

    assert all(f"{name}=" in env_example for name in required)
    assert "replace_with_qq_smtp_authorization_code" in env_example
