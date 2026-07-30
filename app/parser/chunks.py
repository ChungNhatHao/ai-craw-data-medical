import re
from dataclasses import dataclass

from app.models.disease import DiseaseSection

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class MarkdownChunk:
    heading: str
    level: int
    order: int
    markdown: str

    def as_section(self) -> DiseaseSection:
        return DiseaseSection(
            heading=self.heading,
            level=self.level,
            order=self.order,
            markdown=self.markdown,
        )


def chunk_by_heading(markdown: str) -> tuple[MarkdownChunk, ...]:
    chunks: list[MarkdownChunk] = []
    heading = "Document"
    level = 1
    lines: list[str] = []

    def append_chunk() -> None:
        body = "\n".join(lines).strip()
        if not body:
            return
        chunks.append(
            MarkdownChunk(
                heading=heading,
                level=level,
                order=len(chunks) + 1,
                markdown=body,
            )
        )

    for line in markdown.splitlines():
        match = HEADING_PATTERN.match(line)
        if match:
            append_chunk()
            heading = match.group(2).strip()
            level = len(match.group(1))
            lines = [line]
        else:
            lines.append(line)
    append_chunk()
    return tuple(chunks)

