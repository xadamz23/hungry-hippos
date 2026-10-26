"""Import a recipe from a URL: schema.org data first, then Claude as a fallback."""

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MAX_BYTES = 5_000_000
MAX_TEXT_CHARS = 60_000
MAX_REDIRECTS = 5


class RecipeImportError(Exception):
    """An import failure with a message that can be shown to the user as-is."""


@dataclass
class ImportedRecipe:
    title: str
    ingredients: list[str]
    steps: list[str] = field(default_factory=list)
    servings: int | None = None
    total_minutes: int | None = None
    image_url: str | None = None
    source_url: str | None = None


class RecipeExtraction(BaseModel):
    is_recipe: bool = Field(description="False if the page does not contain a recipe")
    title: str
    ingredients: list[str] = Field(description="One ingredient per item, exactly as written, including amounts")
    steps: list[str] = Field(description="Instructions in order, one step per item")
    servings: int | None
    total_minutes: int | None


def ai_enabled() -> bool:
    return bool(get_settings().anthropic_api_key)


# ---------- fetching (with SSRF guard) ----------

def _resolve_host(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RecipeImportError("That doesn’t look like a web link. Paste the full address, starting with https://")
    try:
        addresses = _resolve_host(parts.hostname)
    except OSError:
        raise RecipeImportError("Couldn’t find that website. Check the link and try again.") from None
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global:
            raise RecipeImportError("That link points to a private address, so it can’t be imported.")


def _check_peer(response: httpx.Response) -> None:
    """Re-check the address we actually connected to (guards against DNS rebinding)."""
    stream = response.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream is not None else None
    if addr and not ipaddress.ip_address(str(addr[0]).split("%")[0]).is_global:
        raise RecipeImportError("That link points to a private address, so it can’t be imported.")


def _read_capped(response: httpx.Response) -> bytes:
    too_big = RecipeImportError("That page is too big to import. Add the recipe by hand instead.")
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BYTES:
        raise too_big
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise too_big
    return bytes(body)


def fetch_html(url: str, transport: httpx.BaseTransport | None = None) -> str:
    url = url.strip()
    with httpx.Client(
        transport=transport, timeout=15.0, follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(url)
            try:
                with client.stream("GET", url) as response:
                    _check_peer(response)
                    if response.is_redirect and "location" in response.headers:
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code >= 400:
                        raise RecipeImportError(f"Couldn’t load that page (HTTP {response.status_code}).")
                    body = _read_capped(response)
                    return body.decode(response.encoding or "utf-8", errors="replace")
            except httpx.TimeoutException:
                raise RecipeImportError("That page took too long to load. Try again in a bit.") from None
            except httpx.HTTPError:
                raise RecipeImportError("Couldn’t load that page. Check the link and try again.") from None
    raise RecipeImportError("That link redirects too many times.")


# ---------- structured data ----------

def _safe(fn, default=None):
    try:
        value = fn()
        return value if value not in ("", None) else default
    except Exception:  # recipe-scrapers raises many different errors for missing fields
        return default


def parse_structured(html: str, url: str) -> ImportedRecipe | None:
    from recipe_scrapers import scrape_html

    try:
        scraper = scrape_html(html, org_url=url, supported_only=False)
    except Exception:
        return None
    ingredients = [i.strip() for i in (_safe(scraper.ingredients, []) or []) if i and i.strip()]
    if not ingredients:
        return None
    yields = _safe(scraper.yields, "")
    servings = int(m.group()) if (m := re.search(r"\d+", str(yields))) else None
    total = _safe(scraper.total_time)
    return ImportedRecipe(
        title=_safe(scraper.title, "Imported recipe"),
        ingredients=ingredients,
        steps=[s.strip() for s in (_safe(scraper.instructions_list, []) or []) if s and s.strip()],
        servings=servings,
        total_minutes=int(total) if isinstance(total, (int, float)) and total > 0 else None,
        image_url=_safe(scraper.image),
        source_url=url,
    )


# ---------- Claude fallback ----------

class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


PROMPT = """Extract the recipe from this web page text. Copy ingredient lines exactly as written, \
including amounts and units. Put each instruction step in order. If the page has no recipe, set \
is_recipe to false and leave the lists empty.

Page URL: {url}

<page>
{text}
</page>"""


def parse_with_claude(html: str, url: str, client=None) -> ImportedRecipe:
    import anthropic

    text = page_text(html)
    if len(text) > MAX_TEXT_CHARS:
        raise RecipeImportError("That page is too long to read automatically. Add the recipe by hand instead.")
    client = client or anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    try:
        response = client.beta.messages.parse(
            model=get_settings().anthropic_model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=RecipeExtraction,
            messages=[{"role": "user", "content": PROMPT.format(url=url, text=text)}],
        )
    except anthropic.RateLimitError:
        raise RecipeImportError("Recipe reading is busy right now. Try again in a minute.") from None
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        raise RecipeImportError("Couldn’t read that recipe automatically. Try again, or add it by hand.") from None
    data = response.parsed_output
    if response.stop_reason == "refusal" or data is None:
        raise RecipeImportError("Couldn’t read that recipe automatically. Add it by hand instead.")
    if not data.is_recipe or not data.ingredients:
        raise RecipeImportError("That page doesn’t look like a recipe. Add it by hand instead.")
    return ImportedRecipe(
        title=data.title or "Imported recipe",
        ingredients=[i.strip() for i in data.ingredients if i.strip()],
        steps=[s.strip() for s in data.steps if s.strip()],
        servings=data.servings if data.servings and data.servings > 0 else None,
        total_minutes=data.total_minutes if data.total_minutes and data.total_minutes > 0 else None,
        source_url=url,
    )


def import_url(url: str) -> ImportedRecipe:
    html = fetch_html(url)
    recipe = parse_structured(html, url)
    if recipe is not None:
        return recipe
    if not ai_enabled():
        raise RecipeImportError("This page doesn’t have recipe data we can read. Add it by hand instead.")
    return parse_with_claude(html, url)
