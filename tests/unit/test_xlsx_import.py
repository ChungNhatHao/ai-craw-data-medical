import pytest

from app.services.xlsx_import import (
    build_disease_import_template,
    parse_disease_names_xlsx,
)
from app.storage.artifacts import ArtifactStore


def test_xlsx_template_round_trips_example_disease_names() -> None:
    template = build_disease_import_template()

    assert template.startswith(b"PK")
    assert parse_disease_names_xlsx(template) == (
        "Down syndrome",
        "Sepsis",
    )


def test_xlsx_parser_rejects_invalid_or_empty_payload() -> None:
    with pytest.raises(ValueError, match="1 byte"):
        parse_disease_names_xlsx(b"")

    with pytest.raises(ValueError, match="định dạng XLSX"):
        parse_disease_names_xlsx(b"not-an-xlsx")


def test_import_audit_creates_job_directory_before_item_artifacts(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path / "output")

    path = store.persist_import_search_audit(
        "job-before-fetch",
        {"matched_count": 0, "attempts": []},
    )

    assert path.is_file()
    assert '"matched_count": 0' in path.read_text(encoding="utf-8")
