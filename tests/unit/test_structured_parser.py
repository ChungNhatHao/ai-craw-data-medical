import asyncio

import pytest

from app.core.errors import CrawlerError, ErrorCode
from app.models.disease import PartialDiseaseFields
from app.parser.chunks import chunk_by_heading
from app.parser.structured import (
    RuleBasedStructuredClient,
    disease_schema_hash,
    load_parser_prompt,
    merge_partial_fields,
    missing_field_warnings,
    validate_grounding,
)

MARKDOWN = """# Example disease

I10 * I11.0

Example syndrome * Example condition

Source summary.

## Clinical details

| Column 1 | Column 2 |
| --- | --- |
| Causes | First cause<br>Second cause |
| Symptoms | Source symptom |
| Prognosis | Depending on cause. |

## Treatment

| Column 1 | Column 2 |
| --- | --- |
| Treatment | Source treatment |
"""


def test_chunk_rule_parse_and_merge_are_deterministic() -> None:
    async def scenario() -> None:
        chunks = chunk_by_heading(MARKDOWN)
        client = RuleBasedStructuredClient()
        prompt = load_parser_prompt()
        partials = tuple(
            [
                await client.parse_chunk(chunk=chunk, prompt=prompt)
                for chunk in chunks
            ]
        )
        fields = merge_partial_fields(partials)

        assert [chunk.heading for chunk in chunks] == [
            "Example disease",
            "Clinical details",
            "Treatment",
        ]
        assert [chunk.order for chunk in chunks] == [1, 2, 3]
        assert fields.name == "Example disease"
        assert fields.aliases == ("Example syndrome", "Example condition")
        assert fields.summary == "Source summary."
        assert fields.causes == ("First cause", "Second cause")
        assert fields.symptoms == ("Source symptom",)
        assert fields.treatment == ("Source treatment",)
        assert fields.prognosis == "Depending on cause."
        assert fields.diagnosis == ()
        assert "missing_field:diagnosis" in missing_field_warnings(fields)
        assert "missing_field:summary" not in missing_field_warnings(fields)
        validate_grounding(fields, MARKDOWN)
        assert disease_schema_hash() == disease_schema_hash()
        assert len(disease_schema_hash()) == 64

    asyncio.run(scenario())


def test_grounding_guard_rejects_hallucinated_value() -> None:
    fields = merge_partial_fields(
        (
            PartialDiseaseFields(
                name="Example disease",
                treatment=("Invented treatment",),
            ),
        )
    )

    with pytest.raises(CrawlerError) as captured:
        validate_grounding(fields, MARKDOWN)

    assert captured.value.code is ErrorCode.LLM_OUTPUT_INVALID
    assert "treatment" in str(captured.value)
