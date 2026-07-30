import hashlib

import pytest
from pydantic import ValidationError

from app.models.content import (
    NormalizationInput,
    UnsafeContentPayload,
    assert_safe_content_payload,
)
from app.parser.extractor import ContentExtractor


def test_beautifulsoup_extraction_produces_html_free_agent_input() -> None:
    raw_html = """
    <!doctype html>
    <html><head><script>stealCredentials()</script></head>
    <body><nav>Account menu</nav><main>
      <h1>Example disease</h1>
      <p>Example disease causes a sufficiently long description of symptoms,
      diagnosis, treatment, and expected prognosis for this extraction.</p>
      <a href="javascript:alert(1)">unsafe link</a>
    </main></body></html>
    """
    extracted = ContentExtractor(minimum_chars=50).extract(
        raw_html,
        root_selectors=("main",),
        title_selectors=("h1",),
    )
    normalized = NormalizationInput(
        source_url="https://example.test/disease",
        content_hash=hashlib.sha256(
            extracted.plain_text.encode("utf-8")
        ).hexdigest(),
        title="Example disease",
        plain_text=extracted.plain_text,
    )

    payload = normalized.to_agent_payload()

    assert payload["plain_text"] == extracted.plain_text
    assert "<" not in extracted.plain_text
    assert "stealCredentials" not in extracted.plain_text
    assert "Account menu" not in extracted.plain_text
    assert "javascript:" not in extracted.html
    assert extracted.removed_nodes >= 3


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_html": "<main>Disease</main>"},
        {"request": {"content_html": "<article>Disease</article>"}},
        {"plain_text": "<script>alert(1)</script>"},
        {"messages": [{"text": "<html>Disease</html>"}]},
    ],
)
def test_agent_payload_guard_rejects_html_fields_and_markers(
    payload: dict[str, object],
) -> None:
    with pytest.raises(UnsafeContentPayload):
        assert_safe_content_payload(payload)


def test_normalization_input_rejects_html_and_unknown_raw_field() -> None:
    digest = "a" * 64

    with pytest.raises(ValidationError):
        NormalizationInput(
            source_url="https://example.test/disease",
            content_hash=digest,
            plain_text="<p>Disease content</p>",
        )
    with pytest.raises(ValidationError):
        NormalizationInput.model_validate(
            {
                "source_url": "https://example.test/disease",
                "content_hash": digest,
                "plain_text": "Disease content",
                "raw_html": "<p>Disease content</p>",
            }
        )


def test_agent_payload_guard_allows_plain_markdown_like_text() -> None:
    assert_safe_content_payload(
        {
            "plain_text": "# Disease\n\nTreatment: supportive care.",
            "evidence": ["Symptoms include pain.", "Prognosis varies."],
        }
    )
