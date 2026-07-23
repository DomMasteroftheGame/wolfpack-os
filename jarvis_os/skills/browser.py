"""Browser skill for web search and page fetching."""

import asyncio
from typing import Any

import httpx
from bs4 import BeautifulSoup

from jarvis_os.skills.base import Skill


class BrowserSkill(Skill):
    """Search the web or fetch readable text from a URL."""

    name = "browser"
    description = "Search the web with DuckDuckGo or fetch and extract text from a URL."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "fetch"],
                "description": "Action to perform: search the web or fetch a page.",
            },
            "query": {
                "type": "string",
                "description": "Search query when action is 'search'.",
            },
            "url": {
                "type": "string",
                "description": "URL to fetch when action is 'fetch'.",
            },
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of search results to return.",
            },
        },
        "required": ["action"],
    }
    permissions = ["browser:search", "browser:fetch"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute a browser action."""
        action = kwargs["action"]
        if action == "search":
            return await self._search(kwargs)
        if action == "fetch":
            return await self._fetch(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _search(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        query = kwargs.get("query")
        if not query or not isinstance(query, str):
            return {"error": "query is required for search and must be a non-empty string"}
        max_results = kwargs.get("max_results", 5)
        try:
            from duckduckgo_search import DDGS

            results = await asyncio.to_thread(
                DDGS().text,
                query,
                max_results=max_results,
            )
            return {"query": query, "results": results}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    async def _fetch(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        url = kwargs.get("url")
        if not url or not isinstance(url, str):
            return {"error": "url is required for fetch and must be a non-empty string"}
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else None

        # Remove non-content elements.
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        return {
            "url": str(response.url),
            "title": title,
            "text": "\n".join(lines),
        }
