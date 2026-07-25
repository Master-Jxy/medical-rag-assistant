import pytest

from scripts.validate_online_acceptance_sse import (
    AcceptanceValidationError,
    match_heart_chamber_fact,
    parse_sse,
    validate_acceptance_sse,
)


FILE_NAME = "rag-v121-online-acceptance-sample.txt"


def make_sse(answer_parts: list[str], *, include_source=True, include_done=True) -> str:
    blocks = [
        f'event: token\ndata: {{"content": "{part}"}}\n\n'
        for part in answer_parts
    ]
    if include_source:
        blocks.append(
            "event: sources\n"
            f'data: {{"sources": [{{"file_name": "{FILE_NAME}"}}]}}\n\n'
        )
    if include_done:
        blocks.append('event: done\ndata: {"request_id": "sample"}\n\n')
    return "".join(blocks)


@pytest.mark.parametrize(
    "answer",
    [
        "心脏有四个腔室：左心房、右心房、左心室和右心室。",
        "心脏有 4 个心腔，包括左、右心房与左、右心室。",
        "心脏四腔分别是左房、右房、左室、右室。",
    ],
)
def test_heart_chamber_matcher_accepts_verifiable_equivalent_wording(answer) -> None:
    assert match_heart_chamber_fact(answer) == (True, True)


def test_validator_accepts_current_content_field_and_required_evidence() -> None:
    result = validate_acceptance_sse(
        make_sse(
            [
                "心脏有4个腔室：左心房、右心房、",
                "左心室和右心室。",
            ]
        ),
        expected_source_file_name=FILE_NAME,
    )

    assert result.token_event_count == 2
    assert result.source_count == 1
    assert "左心房" in result.answer_content


def test_validator_rejects_obsolete_token_field_instead_of_silently_empty_answer() -> None:
    sse = (
        'event: token\ndata: {"token": "心脏有四个腔室：左心房、右心房、'
        '左心室和右心室。"}\n\n'
        f'event: sources\ndata: {{"sources": [{{"file_name": "{FILE_NAME}"}}]}}\n\n'
        'event: done\ndata: {"request_id": "sample"}\n\n'
    )

    with pytest.raises(AcceptanceValidationError, match="token_content_missing"):
        validate_acceptance_sse(sse, expected_source_file_name=FILE_NAME)


@pytest.mark.parametrize(
    ("sse", "error"),
    [
        (make_sse(["心脏有四个腔室。"]), "heart_chamber_names_missing"),
        (
            make_sse(["左心房、右心房、左心室和右心室。"]),
            "heart_chamber_count_missing",
        ),
        (
            make_sse(
                ["心脏有四个腔室：左心房、右心房、左心室和右心室。"],
                include_source=False,
            ),
            "sources_event_missing",
        ),
        (
            make_sse(
                ["心脏有四个腔室：左心房、右心房、左心室和右心室。"],
                include_done=False,
            ),
            "done_event_missing",
        ),
    ],
)
def test_validator_rejects_missing_required_evidence(sse, error) -> None:
    with pytest.raises(AcceptanceValidationError, match=error):
        validate_acceptance_sse(sse, expected_source_file_name=FILE_NAME)


def test_parser_handles_crlf_and_rejects_invalid_json() -> None:
    assert parse_sse('event: done\r\ndata: {"request_id": "sample"}\r\n\r\n') == [
        ("done", {"request_id": "sample"})
    ]
    with pytest.raises(AcceptanceValidationError, match="invalid_sse_json"):
        parse_sse("event: token\ndata: {bad}\n\n")
