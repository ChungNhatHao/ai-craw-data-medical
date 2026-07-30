import re
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)

PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "agentic"
RAW_DOCUMENT_PATTERN = re.compile(
    r"<!doctype|<\s*(?:html|head|body|script|style|form)\b",
    flags=re.IGNORECASE,
)


class StructuredAgentClient(Protocol):
    """Minimal adapter boundary implemented by Gemini or an offline fake."""

    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: type[StructuredResult],
    ) -> StructuredResult: ...


class AgentContractError(ValueError):
    """A model response or content payload violated an agent boundary."""


def load_agent_prompt(filename: str) -> str:
    return (PROMPT_ROOT / filename).read_text(encoding="utf-8").strip()


def reject_raw_document(value: str, *, field_name: str) -> None:
    if RAW_DOCUMENT_PATTERN.search(value):
        raise AgentContractError(
            f"{field_name} contains raw-document markup; "
            "run BeautifulSoup cleaning before calling a content agent"
        )


def normalized_evidence(value: str) -> str:
    return " ".join(value.split()).casefold()
