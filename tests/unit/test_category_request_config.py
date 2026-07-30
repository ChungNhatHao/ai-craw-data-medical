import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.run import RunRequest

BASE_REQUEST = {
    "url": "https://www.genre-manuals.com/sites/CLUE/home.html",
    "username": "user",
    "password": "secret",
    "authorization_confirmed": True,
}


def test_old_run_request_gets_backward_compatible_category_defaults() -> None:
    request = RunRequest.model_validate(BASE_REQUEST)

    assert request.discovery_mode == "automatic"
    assert request.expand_disease_categories is True
    assert request.category_max_depth == 5
    assert request.category_max_nodes == 100
    assert request.category_max_diseases == 100
    assert request.disease_names == ()


def test_import_category_options_preserve_normalized_roots() -> None:
    request = RunRequest.model_validate(
        {
            **BASE_REQUEST,
            "discovery_mode": "import",
            "disease_names": [
                "  Cardiac   arrhythmia ",
                "cardiac arrhythmia",
            ],
            "expand_disease_categories": False,
            "category_max_depth": 8,
            "category_max_nodes": 250,
            "category_max_diseases": 250,
        }
    )

    assert request.disease_names == ("Cardiac arrhythmia",)
    assert request.max_items == 1
    assert request.expand_disease_categories is False


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("category_max_depth", 0),
        ("category_max_depth", 9),
        ("category_max_nodes", 0),
        ("category_max_nodes", 251),
        ("category_max_diseases", 0),
        ("category_max_diseases", 251),
    ],
)
def test_run_request_rejects_category_limits_outside_hard_bounds(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                **BASE_REQUEST,
                field_name: invalid_value,
            }
        )


def test_settings_exposes_fixed_category_hard_limits() -> None:
    settings = Settings(_env_file=None)

    assert settings.category_hard_max_depth == 8
    assert settings.category_hard_max_nodes == 250
    assert settings.category_hard_max_diseases == 250

    with pytest.raises(ValidationError):
        Settings(_env_file=None, category_hard_max_depth=9)
