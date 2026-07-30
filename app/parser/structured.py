import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Protocol

from app.core.errors import CrawlerError, ErrorCode
from app.models.disease import DiseaseDocument, DiseaseFields, PartialDiseaseFields
from app.parser.chunks import MarkdownChunk

PARSER_VERSION = "1.0.3"
PROMPT_VERSION = "1.0.0"
PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "parser_v1.md"
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKUP_PATTERN = re.compile(r"[*_`#>|]")
SPACE_PATTERN = re.compile(r"\s+")
ICD_CODE_PATTERN = re.compile(r"^[A-Z]\d[\dA-Z.]*$")

LIST_FIELDS = (
    "aliases",
    "causes",
    "risk_factors",
    "symptoms",
    "diagnosis",
    "treatment",
    "prevention",
    "when_to_seek_care",
)
SCALAR_FIELDS = ("summary", "prognosis")
TABLE_FIELD_MAP = {
    "aliases": "aliases",
    "also known as": "aliases",
    "summary": "summary",
    "overview": "summary",
    "causes": "causes",
    "risk factors": "risk_factors",
    "symptoms": "symptoms",
    "diagnosis": "diagnosis",
    "diagnostic": "diagnosis",
    "treatment": "treatment",
    "prevention": "prevention",
    "prognosis": "prognosis",
    "when to seek care": "when_to_seek_care",
}


class StructuredModelClient(Protocol):
    method: str
    model_id: str | None
    supports_repair: bool

    async def parse_chunk(
        self,
        *,
        chunk: MarkdownChunk,
        prompt: str,
    ) -> PartialDiseaseFields: ...

    async def repair(
        self,
        *,
        markdown: str,
        prompt: str,
        validation_error: str,
    ) -> PartialDiseaseFields: ...


class RuleBasedStructuredClient:
    method = "rules"
    model_id: str | None = None
    supports_repair = False

    async def parse_chunk(
        self,
        *,
        chunk: MarkdownChunk,
        prompt: str,
    ) -> PartialDiseaseFields:
        del prompt
        values: dict[str, object] = {}
        title = HEADING_PATTERN.search(chunk.markdown)
        if title:
            name = _plain_text(title.group(1))
            values["name"] = name
            values.update(_extract_intro_fields(chunk.markdown, name))

        for line in chunk.markdown.splitlines():
            if not line.startswith("|") or line.count("|") < 3:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= {"-", ":"}:
                continue
            label = _plain_text(cells[0]).casefold()
            field = TABLE_FIELD_MAP.get(label)
            value = cells[1].strip()
            if field is None or not value or set(value) <= {"-", ":"}:
                continue
            if field in SCALAR_FIELDS:
                values.setdefault(field, value)
            else:
                existing = values.get(field)
                current = list(existing) if isinstance(existing, tuple) else []
                current.extend(part.strip() for part in value.split("<br>") if part.strip())
                values[field] = tuple(current)
        return PartialDiseaseFields.model_validate(values)

    async def repair(
        self,
        *,
        markdown: str,
        prompt: str,
        validation_error: str,
    ) -> PartialDiseaseFields:
        del markdown, prompt, validation_error
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            "Rule parser does not support model repair",
        )


def load_parser_prompt() -> str:
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            "Versioned parser prompt is unavailable",
        ) from exc
    if not prompt:
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            "Versioned parser prompt is empty",
        )
    return prompt


def merge_partial_fields(
    partials: tuple[PartialDiseaseFields, ...],
) -> DiseaseFields:
    names = _deduplicate(
        tuple(partial.name for partial in partials if partial.name)
    )
    if not names:
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            "Structured output is missing the required disease name",
        )
    if len(names) > 1:
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            "Structured output contains conflicting disease names",
        )

    merged: dict[str, object] = {"name": names[0]}
    for field in LIST_FIELDS:
        merged[field] = _deduplicate(
            tuple(
                value
                for partial in partials
                for value in getattr(partial, field)
            )
        )
    for field in SCALAR_FIELDS:
        values = _deduplicate(
            tuple(
                value
                for partial in partials
                if (value := getattr(partial, field)) is not None
            )
        )
        merged[field] = values[0] if values else None
    return DiseaseFields.model_validate(merged)


def validate_grounding(fields: DiseaseFields, markdown: str) -> None:
    grounded_source = _ground_text(markdown)
    unsupported: list[str] = []
    for field, value in fields:
        values = value if isinstance(value, tuple) else (value,)
        for candidate in values:
            if candidate is None:
                continue
            grounded_value = _ground_text(str(candidate))
            if grounded_value and grounded_value not in grounded_source:
                unsupported.append(field)
    if unsupported:
        names = ", ".join(dict.fromkeys(unsupported))
        raise CrawlerError(
            ErrorCode.LLM_OUTPUT_INVALID,
            f"Structured values are not grounded in source Markdown: {names}",
        )


def disease_schema_hash() -> str:
    canonical = json.dumps(
        DiseaseDocument.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def missing_field_warnings(fields: DiseaseFields) -> tuple[str, ...]:
    return tuple(
        f"missing_field:{field}"
        for field, value in fields
        if field != "name" and value in (None, ())
    )


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _ground_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value.strip())
    return tuple(output)


def _plain_text(value: str) -> str:
    return SPACE_PATTERN.sub(
        " ",
        MARKUP_PATTERN.sub("", LINK_PATTERN.sub(r"\1", value)),
    ).strip()


def _ground_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("<br>", " ")
    return _plain_text(normalized).casefold()


def _extract_intro_fields(markdown: str, disease_name: str) -> dict[str, object]:
    before_table = markdown.split("\n|", 1)[0]
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", before_table)
        if block.strip()
    ]
    aliases: list[str] = []
    summary_blocks: list[str] = []
    for block in blocks[1:]:
        plain = _plain_text(block)
        if not plain:
            continue
        star_parts = tuple(
            _plain_text(part)
            for part in re.split(r"\s+\*\s+", block)
            if _plain_text(part)
        )
        if star_parts and all(ICD_CODE_PATTERN.fullmatch(part) for part in star_parts):
            continue
        if len(star_parts) > 1:
            aliases.extend(
                part
                for part in star_parts
                if _ground_text(part) != _ground_text(disease_name)
            )
            continue
        summary_blocks.append(block)

    output: dict[str, object] = {}
    if aliases:
        output["aliases"] = tuple(aliases)
    if summary_blocks:
        output["summary"] = " ".join(summary_blocks)
    return output
