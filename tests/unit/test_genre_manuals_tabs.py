from app.models.tabs import RawDiseaseTab
from app.plugins.genre_manuals.plugin import GenreManualsPlugin


def _tab(key: str, *, html: str = "<table><tr><td>Data</td></tr></table>") -> RawDiseaseTab:
    return RawDiseaseTab.model_validate(
        {
            "key": key,
            "label": key,
            "source_url": "https://www.genre-manuals.com/disease.html",
            "html": html,
        }
    )


def test_genre_manuals_requires_all_four_nonempty_tabs() -> None:
    plugin = GenreManualsPlugin(base_url="https://www.genre-manuals.com/home.html")
    complete = tuple(_tab(key) for key in ("info", "life_dd_tpd", "ip", "health"))

    assert plugin.raw_tabs_complete(complete)
    assert not plugin.raw_tabs_complete(complete[:-1])
    assert not plugin.raw_tabs_complete((*complete[:-1], _tab("health", html="")))
