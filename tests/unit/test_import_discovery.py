import asyncio
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.core.ids import build_item_id
from app.models.run import RunRequest
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.items import ItemRepository
from app.services.import_discovery import (
    ImportedDiseaseDiscoveryService,
    SearchOutcome,
)
from app.storage.artifacts import ArtifactStore

BASE_URL = "https://www.genre-manuals.com/sites/CLUE/home.html"


def test_import_request_normalizes_deduplicates_and_sets_limit() -> None:
    request = RunRequest(
        url=BASE_URL,
        username="user",
        password="secret",
        discovery_mode="import",
        disease_names=(" Sepsis ", "Down   syndrome", "sepsis", ""),
        authorization_confirmed=True,
    )

    assert request.disease_names == ("Sepsis", "Down syndrome")
    assert request.max_items == 2


def test_import_request_requires_names_and_enforces_limit() -> None:
    with pytest.raises(ValidationError, match="ít nhất một tên bệnh"):
        RunRequest(
            url=BASE_URL,
            username="user",
            password="secret",
            discovery_mode="import",
            authorization_confirmed=True,
        )

    with pytest.raises(ValidationError, match="tối đa 25"):
        RunRequest(
            url=BASE_URL,
            username="user",
            password="secret",
            discovery_mode="import",
            disease_names=tuple(f"Disease {index}" for index in range(26)),
            authorization_confirmed=True,
        )


def test_import_selector_only_accepts_exact_same_domain_result() -> None:
    plugin = GenreManualsPlugin(base_url=BASE_URL)
    service = ImportedDiseaseDiscoveryService(
        plugin=plugin,
        items=Mock(spec=ItemRepository),
        artifacts=Mock(spec=ArtifactStore),
    )
    html = """
    <main>
      <a href="/en_down_syndrome.htm">Down syndrome</a>
      <a href="/en_other_syndrome.htm">Other Down syndrome guidance</a>
      <a href="https://example.org/down">Down syndrome</a>
    </main>
    """

    selected = service.select_exact_candidate(
        html,
        query="Down Syndrome",
        result_page="https://www.genre-manuals.com/search_result.htm?q=down",
    )

    assert selected is not None
    assert selected.title_hint == "Down syndrome"
    assert str(selected.canonical_url) == (
        "https://www.genre-manuals.com/en_down_syndrome.htm"
    )


def test_import_selector_does_not_guess_approximate_result() -> None:
    plugin = GenreManualsPlugin(base_url=BASE_URL)
    service = ImportedDiseaseDiscoveryService(
        plugin=plugin,
        items=Mock(spec=ItemRepository),
        artifacts=Mock(spec=ArtifactStore),
    )

    selected = service.select_exact_candidate(
        '<a href="/en_down_syndrome.htm">Down syndrome overview</a>',
        query="Down syndrome",
        result_page="https://www.genre-manuals.com/search_result.htm",
    )

    assert selected is None


def test_import_selector_accepts_exact_alias_and_uses_canonical_title() -> None:
    plugin = GenreManualsPlugin(base_url=BASE_URL)
    service = ImportedDiseaseDiscoveryService(
        plugin=plugin,
        items=Mock(spec=ItemRepository),
        artifacts=Mock(spec=ArtifactStore),
    )

    scan = service.analyze_exact_candidates(
        (
            '<a href="/cad.htm">'
            "Angina pectoris - Coronary artery disease"
            "</a>"
        ),
        query="Angina pectoris",
        result_page="https://www.genre-manuals.com/search_result.htm",
    )

    assert scan.candidate is not None
    assert scan.candidate.title_hint == "Coronary artery disease"
    assert scan.strategy == "alias_exact"


def test_autocomplete_aliases_resolve_to_canonical_search_names_and_dedupe() -> None:
    resolved = ImportedDiseaseDiscoveryService.resolve_autocomplete_labels(
        (
            "Angina pectoris - Coronary artery disease",
            "Aortic stenosis - Aortic valve stenosis",
            "Aortic valve stenosis",
            "COVID-19",
        )
    )

    assert resolved == (
        "Coronary artery disease",
        "Aortic valve stenosis",
        "COVID-19",
    )


def test_imported_search_queries_split_explicit_slash_aliases() -> None:
    assert ImportedDiseaseDiscoveryService.imported_search_queries(
        "Hypertension / High blood pressure"
    ) == (
        "Hypertension / High blood pressure",
        "Hypertension",
        "High blood pressure",
    )
    assert ImportedDiseaseDiscoveryService.imported_search_queries(
        "HIV/AIDS"
    ) == ("HIV/AIDS",)


def test_search_variants_retry_each_explicit_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ImportedDiseaseDiscoveryService(
        plugin=GenreManualsPlugin(base_url=BASE_URL),
        items=Mock(spec=ItemRepository),
        artifacts=Mock(spec=ArtifactStore),
    )
    submitted: list[str] = []

    async def fake_search(page: object, query: str) -> SearchOutcome:
        del page
        submitted.append(query)
        return SearchOutcome(
            url="https://www.genre-manuals.com/search_result.htm",
            reason_code=None,
            reason=None,
            steps=(f"searched:{query}",),
            submitted_query=query,
            result_html="<main></main>",
        )

    monkeypatch.setattr(service, "_search", fake_search)
    outcomes = asyncio.run(
        service._search_variants(
            object(),  # type: ignore[arg-type]
            "Hypertension / High blood pressure",
        )
    )

    assert submitted == [
        "Hypertension / High blood pressure",
        "Hypertension",
        "High blood pressure",
    ]
    assert tuple(outcome.submitted_query for outcome in outcomes) == tuple(
        submitted
    )


def test_search_variants_submit_every_autocomplete_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ImportedDiseaseDiscoveryService(
        plugin=GenreManualsPlugin(base_url=BASE_URL),
        items=Mock(spec=ItemRepository),
        artifacts=Mock(spec=ArtifactStore),
    )
    resolved = tuple(f"Disease {index}" for index in range(1, 13))
    submitted: list[str] = []

    async def fake_search(page: object, query: str) -> SearchOutcome:
        del page, query
        return SearchOutcome(
            url="https://www.genre-manuals.com/search_result.htm",
            reason_code=None,
            reason=None,
            steps=("collected all suggestions",),
            submitted_query=resolved[0],
            resolved_suggestions=resolved,
            selected_suggestions=resolved,
            decision_source="all_suggestions",
            result_html="<main></main>",
        )

    async def fake_submit(
        page: object,
        query: str,
        *,
        primary: SearchOutcome,
    ) -> SearchOutcome:
        del page, primary
        submitted.append(query)
        return SearchOutcome(
            url="https://www.genre-manuals.com/search_result.htm",
            reason_code=None,
            reason=None,
            steps=(f"searched:{query}",),
            submitted_query=query,
            result_html="<main></main>",
        )

    monkeypatch.setattr(service, "_search", fake_search)
    monkeypatch.setattr(service, "_submit_search_query", fake_submit)

    outcomes = asyncio.run(
        service._search_variants(
            object(),  # type: ignore[arg-type]
            "Imported disease",
        )
    )

    assert submitted == list(resolved[1:])
    assert tuple(outcome.submitted_query for outcome in outcomes) == resolved


def test_import_run_skips_disease_completed_in_previous_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = GenreManualsPlugin(base_url=BASE_URL)
    items = Mock(spec=ItemRepository)
    artifacts = Mock(spec=ArtifactStore)
    service = ImportedDiseaseDiscoveryService(
        plugin=plugin,
        items=items,
        artifacts=artifacts,
    )
    disease_url = "https://www.genre-manuals.com/en_hypertension.htm"
    completed_id = build_item_id(plugin.name, disease_url)
    items.list_completed_item_ids.return_value = {completed_id}

    async def fake_variants(
        page: object,
        disease_name: str,
    ) -> tuple[SearchOutcome, ...]:
        del page, disease_name
        return (
            SearchOutcome(
                url="https://www.genre-manuals.com/search_result.htm",
                reason_code=None,
                reason=None,
                steps=("searched",),
                submitted_query="Hypertension",
                result_html=(
                    '<a href="/en_hypertension.htm">Hypertension</a>'
                ),
            ),
        )

    async def fail_confirmation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("completed disease must not be reconfirmed")

    async def progress(*args: object) -> None:
        del args

    monkeypatch.setattr(service, "_search_variants", fake_variants)
    monkeypatch.setattr(service, "_confirm_detail", fail_confirmation)

    selected, unmatched = asyncio.run(
        service.run(
            object(),  # type: ignore[arg-type]
            job_id="current-job",
            disease_names=("Hypertension",),
            progress=progress,
        )
    )

    assert selected == []
    assert unmatched == ()
    items.upsert_discovered.assert_awaited_once_with("current-job", [])
    audit = artifacts.persist_import_search_audit.call_args.args[1]
    assert audit["attempts"][0]["skipped_existing_count"] == 1
    assert audit["attempts"][0]["reason_code"] == (
        "autocomplete_candidates_already_completed"
    )
