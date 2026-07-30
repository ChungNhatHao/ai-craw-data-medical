LOGIN_FORM = "#loginForm"
USERNAME_INPUT = "#username"
PASSWORD_INPUT = "#password"
REMEMBER_ME = "#rememberme"
SUBMIT = '#loginForm input[type="submit"]'

LOGIN_ERROR = (
    ".loginError, .errorMessage, .alert-error, .alert-danger, "
    "[data-login-error='true']"
)
MFA_OR_CAPTCHA = (
    "iframe[src*='captcha' i], [class*='captcha' i], [id*='captcha' i], "
    "input[autocomplete='one-time-code'], input[name*='otp' i]"
)
AUTHENTICATED_CONTENT = (
    "a[href*='logout' i], form[action*='logout' i], "
    ".genreContent, main, #content, [data-authenticated='true']"
)

BLOCKED_OR_CAPTCHA = (
    "iframe[src*='captcha' i], [class*='captcha' i], [id*='captcha' i], "
    "[class*='access-denied' i], [data-blocked='true']"
)
PAGE_TITLE = "h1, h2.pageTitle, main h2, #content h2"
CONTENT_ROOT = ".genrearticle, article, main .content, [data-disease-content='true']"
BREADCRUMB = "ul.breadcrumb, nav[aria-label*='breadcrumb' i], .breadcrumbs"
NAVIGATION_LINKS = (
    "#sidemenutree a[href], nav a[href], main a[href], #content a[href]"
)
NEXT_PAGE = (
    "a[rel='next'][href], .pagination .next:not(.disabled) a[href], "
    "a.next:not(.disabled)[href], [data-pagination-next][href]"
)
KNOWN_POPUP_CLOSE = (
    "button[aria-label='Close'], button[aria-label='Dismiss'], "
    ".modal .close, .cookie-banner button[data-action='accept']"
)
