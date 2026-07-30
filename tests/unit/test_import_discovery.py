from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.run import RunRequest
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.items import ItemRepository
from app.services.import_discovery import ImportedDiseaseDiscoveryService
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
