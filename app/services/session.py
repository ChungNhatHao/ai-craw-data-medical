from dataclasses import dataclass

from playwright.async_api import Browser

from app.browser.session import SessionStore
from app.core.config import Credentials
from app.core.errors import CrawlerError, ErrorCode
from app.plugins.base import SitePlugin


@dataclass(frozen=True)
class LoginResult:
    reused_session: bool


class SessionService:
    def __init__(self, plugin: SitePlugin, store: SessionStore) -> None:
        self.plugin = plugin
        self.store = store

    async def ensure_authenticated(
        self,
        browser: Browser,
        credentials: Credentials,
    ) -> LoginResult:
        stored_state = self.store.load()
        context = await browser.new_context(storage_state=stored_state)
        try:
            page = await context.new_page()
            if await self.plugin.validate_session(page):
                return LoginResult(reused_session=True)
            await self.plugin.login(page, credentials)
            if not await self.plugin.validate_session(page):
                raise CrawlerError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "Plugin login did not create a valid session",
                )
            self.store.save(await context.storage_state())
            return LoginResult(reused_session=False)
        finally:
            await context.close()
