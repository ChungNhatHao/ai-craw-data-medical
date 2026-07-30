from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


class FixtureResponse:
    status = 200


class FixtureLocator:
    def __init__(
        self,
        page: "FixturePage",
        selector: str,
        index: int | None = None,
    ) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def _elements(self) -> list[Any]:
        elements = self.page.soup.select(self.selector)
        if self.index is None:
            return elements
        return elements[self.index : self.index + 1]

    @property
    def first(self) -> "FixtureLocator":
        return FixtureLocator(self.page, self.selector, 0)

    def nth(self, index: int) -> "FixtureLocator":
        return FixtureLocator(self.page, self.selector, index)

    async def count(self) -> int:
        return len(self._elements())

    async def fill(self, value: str) -> None:
        element = self._elements()[0]
        element["value"] = value
        name = str(element.get("name"))
        self.page.filled[name] = value

    async def is_checked(self) -> bool:
        return "checked" in self._elements()[0].attrs

    async def check(self) -> None:
        self._elements()[0]["checked"] = "checked"

    async def inner_text(self) -> str:
        return self._elements()[0].get_text(" ", strip=True)

    async def get_attribute(self, name: str) -> str | None:
        value = self._elements()[0].get(name)
        return str(value) if value is not None else None

    async def click(self, *, timeout: int) -> None:  # noqa: ASYNC109
        assert timeout > 0
        element = self._elements()[0]
        if element.get("type") == "submit":
            self.page.submit()
        else:
            element.extract()


class FixturePage:
    def __init__(
        self,
        fixture_root: Path,
        initial_fixture: str,
        *,
        initial_url: str = "https://www.genre-manuals.com/sites/CLUE/home.html",
        route_fixtures: dict[str, str] | None = None,
        accepted_username: str = "valid-user",
        accepted_password: str = "valid-password",
    ) -> None:
        self.fixture_root = fixture_root
        self.initial_fixture = initial_fixture
        self.accepted_username = accepted_username
        self.accepted_password = accepted_password
        self.url = initial_url
        self.route_fixtures = route_fixtures or {}
        self.filled: dict[str, str] = {}
        self._load(initial_fixture)

    def _load(self, fixture: str) -> None:
        content = (self.fixture_root / fixture).read_text(encoding="utf-8")
        self.soup = BeautifulSoup(content, "html.parser")

    async def goto(  # noqa: ASYNC109
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,  # noqa: ASYNC109
    ) -> FixtureResponse:
        assert wait_until == "domcontentloaded"
        assert timeout > 0
        self.url = url
        fixture = self.route_fixtures.get(url, self.initial_fixture)
        self.initial_fixture = fixture
        self._load(fixture)
        return FixtureResponse()

    def locator(self, selector: str) -> FixtureLocator:
        return FixtureLocator(self, selector)

    def submit(self) -> None:
        if (
            self.filled.get("username") == self.accepted_username
            and self.filled.get("password") == self.accepted_password
        ):
            self.initial_fixture = "authenticated.html"
        else:
            self.initial_fixture = "invalid_credentials.html"
        self._load(self.initial_fixture)

    async def wait_for_load_state(  # noqa: ASYNC109
        self,
        state: str,
        *,
        timeout: int,  # noqa: ASYNC109
    ) -> None:
        assert state == "domcontentloaded"
        assert timeout > 0
