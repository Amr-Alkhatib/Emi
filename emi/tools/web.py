"""Web search (DuckDuckGo, no key needed), reading pages, opening links."""
from __future__ import annotations

import re
import webbrowser
from urllib.parse import quote_plus, urlparse

from . import ToolError, tool

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
SAFE_SCHEMES = {"http", "https", "spotify", "steam", "discord", "mailto", "ms-settings", "zoommtg", "msteams"}


@tool("web_search", "Search the web for current information (news, prices, weather, scores, facts, how-tos). "
      "Returns titles, snippets and links.",
      {"query": {"type": "string"}}, ["query"], label=lambda a: f"Searching: {a.get('query')}")
def web_search(ctx, a):
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # older package name
    try:
        results = DDGS().text(str(a["query"]), max_results=6) or []
    except Exception as e:
        raise ToolError(f"Search failed ({type(e).__name__}). Try again in a moment.")
    if not results:
        return "No results."
    return "\n\n".join(f"{r.get('title')}\n{r.get('body')}\n{r.get('href')}" for r in results)


@tool("fetch_page", "Read the text of a web page (use after web_search to get details from a result).",
      {"url": {"type": "string"}}, ["url"], label="Reading a web page")
def fetch_page(ctx, a):
    import httpx
    from bs4 import BeautifulSoup
    url = str(a["url"]).strip()
    if urlparse(url).scheme not in ("http", "https"):
        raise ToolError("Only http(s) links can be read.")
    r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    text = re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n"))
    text = re.sub(r"[ \t]+", " ", text).strip()
    return f"{title}\n{url}\n\n{text[:8000]}"


@tool("open_url", "Open a website or link in the default browser. If the user names a site, build its URL. "
      "For a search on a site (e.g. YouTube), use that site's search URL.",
      {"url": {"type": "string"}}, ["url"], label=lambda a: f"Opening {urlparse(str(a.get('url'))).netloc or a.get('url')}")
def open_url(ctx, a):
    url = str(a["url"]).strip()
    if "://" not in url and ":" not in url.split("/")[0]:
        url = "https://" + url
    scheme = urlparse(url).scheme.lower()
    if scheme not in SAFE_SCHEMES:
        raise ToolError(f"I don't open '{scheme}:' links.")
    webbrowser.open(url)
    return f"Opened {url}"


def youtube_search_url(q: str) -> str:  # handy for routines
    return "https://www.youtube.com/results?search_query=" + quote_plus(q)
