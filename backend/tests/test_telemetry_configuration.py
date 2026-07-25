from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_compose_passes_telemetry_configuration_to_backend() -> None:
    compose_text = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    expected_entries = (
        "TELEMETRY_ENABLED: ${TELEMETRY_ENABLED:-true}",
        "TELEMETRY_LOG_PATH: ${TELEMETRY_LOG_PATH:-/app/data/logs/telemetry.jsonl}",
        "TELEMETRY_LOG_MAX_BYTES: ${TELEMETRY_LOG_MAX_BYTES:-5242880}",
        "TELEMETRY_LOG_BACKUP_COUNT: ${TELEMETRY_LOG_BACKUP_COUNT:-5}",
    )

    for entry in expected_entries:
        assert entry in compose_text


def test_deployment_example_documents_telemetry_configuration() -> None:
    env_example = (PROJECT_ROOT / "deploy" / ".env.example").read_text(
        encoding="utf-8"
    )

    expected_entries = (
        "TELEMETRY_ENABLED=true",
        "TELEMETRY_LOG_PATH=/app/data/logs/telemetry.jsonl",
        "TELEMETRY_LOG_MAX_BYTES=5242880",
        "TELEMETRY_LOG_BACKUP_COUNT=5",
    )

    for entry in expected_entries:
        assert entry in env_example
