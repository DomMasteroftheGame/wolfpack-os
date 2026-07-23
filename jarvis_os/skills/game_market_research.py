"""Game market research skill.

Finds trending game concepts, genres, and mechanics that players want. Uses
web search + page fetching, with fallback sources when search engines block us.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

_GAME_TREND_QUERIES = [
    "trending games 2025 2026 people want to play",
    "most anticipated indie games",
    "popular Roblox games 2025",
    "best selling Steam games this month",
    "TikTok viral games",
]

_GAME_FALLBACKS = [
    {"url": "https://deltiasgaming.com/top-10-roblox-games-you-should-be-playing-in-2025/", "title": "Top Roblox Games 2025"},
    {"url": "https://www.pcgamer.com/upcoming-games/", "title": "PC Gamer Upcoming Games"},
    {"url": "https://www.ign.com/articles/upcoming-games", "title": "IGN Upcoming Games"},
    {"url": "https://store.steampowered.com/charts/mostplayed", "title": "Steam Most Played"},
]


class GameMarketResearchSkill(Skill):
    """Research trending games and player demand."""

    name = "game_market_research"
    description = (
        "Research trending games, popular genres, and player demand on Steam, "
        "Roblox, TikTok, and gaming news sites. Generates game concept recommendations."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["find_trending_games", "research_genre", "generate_game_concept"],
                "description": "Market research action.",
            },
            "genre": {
                "type": "string",
                "description": "Specific genre to research (e.g. 'survival horror').",
            },
            "platform": {
                "type": "string",
                "enum": ["steam", "roblox", "mobile", "console", "pc"],
                "default": "steam",
            },
            "findings": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Prior findings to synthesize into a game concept.",
            },
        },
        "required": ["action"],
    }
    permissions = ["browser:search", "browser:fetch"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "find_trending_games":
            return await self._find_trending(kwargs)
        if action == "research_genre":
            return await self._research_genre(kwargs)
        if action == "generate_game_concept":
            return await self._generate_concept(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _find_trending(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        max_results = kwargs.get("max_results", 8)
        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for query in _GAME_TREND_QUERIES:
            results = await self._ddg_search(query, max_results=max_results)
            for r in results:
                url = r.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append({
                    "title": r.get("title"),
                    "url": url,
                    "snippet": r.get("snippet"),
                    "source": self._source_from_url(url),
                })

        fetched = await asyncio.gather(*[self._fetch_page(r["url"], full=True) for r in all_results[:5]])
        for r, data in zip(all_results[:5], fetched):
            r["page_data"] = data

        if not all_results:
            logger.warning("DDG returned no game results; using fallback sources.")
            for src in _GAME_FALLBACKS:
                all_results.append({
                    "title": src["title"],
                    "url": src["url"],
                    "snippet": "Fallback source for trending games.",
                    "source": self._source_from_url(src["url"]),
                    "page_data": await self._fetch_page(src["url"], full=True),
                })

        return {
            "action": "find_trending_games",
            "query_count": len(_GAME_TREND_QUERIES),
            "result_count": len(all_results),
            "results": all_results,
        }

    async def _research_genre(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        genre = kwargs.get("genre", "")
        platform = kwargs.get("platform", "steam")
        if not genre:
            return {"error": "genre is required for research_genre"}

        queries = [
            f"best {genre} games {platform}",
            f"top {genre} games 2025",
            f"{genre} games trending on {platform}",
            f"why {genre} games are popular",
        ]

        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for query in queries:
            results = await self._ddg_search(query, max_results=6)
            for r in results:
                url = r.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append({
                    "title": r.get("title"),
                    "url": url,
                    "snippet": r.get("snippet"),
                    "source": self._source_from_url(url),
                })

        fetched = await asyncio.gather(*[self._fetch_page(r["url"], full=True) for r in all_results[:5]])
        for r, data in zip(all_results[:5], fetched):
            r["page_data"] = data

        return {
            "action": "research_genre",
            "genre": genre,
            "platform": platform,
            "result_count": len(all_results),
            "results": all_results,
        }

    async def _generate_concept(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        findings = kwargs.get("findings", [])
        if not findings:
            return {"error": "findings are required for generate_game_concept"}

        game_names = self._extract_game_headings(findings)
        genres = self._extract_genres(findings)

        concept = {
            "genre_focus": genres[0] if genres else "indie arcade",
            "game_names_found": game_names[:10],
            "recommended_mechs": [
                "Roguelike progression with permadeath",
                "Procedural level generation",
                "Co-op multiplayer",
                "Daily challenges / leaderboards",
                "Mod support",
            ],
            "monetization_ideas": [
                "Premium one-time purchase",
                "Cosmetic DLC",
                "Battle pass for seasonal content",
                "Free-to-play with ad removal",
            ],
            "platform_recommendation": "Start with PC/Steam, then port to Roblox or mobile if viral.",
            "next_steps": [
                "Lock core loop and one unique mechanic",
                "Create a vertical slice / prototype",
                "Build a Steam page with trailer",
                "Run a playtest on Reddit/Discord",
                "Plan a Roblox version for younger audience",
            ],
        }

        if game_names:
            concept["concept_pitch"] = (
                f"A {concept['genre_focus']} game that blends the best of "
                f"{', '.join(game_names[:3])} with a fresh hook."
            )
        else:
            concept["concept_pitch"] = f"A fresh {concept['genre_focus']} game with a unique hook."

        return {
            "action": "generate_game_concept",
            "concept": concept,
            "based_on_findings": len(findings),
        }

    async def _ddg_search(self, query: str, max_results: int = 8) -> list[dict[str, str]]:
        from urllib.parse import quote_plus

        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(
                    search_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("DDG search failed for %r: %s", query, exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, str]] = []
        for result in soup.select(".result"):
            title_tag = result.select_one(".result__title .result__a")
            snippet_tag = result.select_one(".result__snippet")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            real_url = self._extract_real_url(href)
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            results.append({"title": title, "url": real_url or href, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results

    def _extract_real_url(self, href: str) -> str | None:
        from urllib.parse import unquote, urlparse, parse_qs

        if not href:
            return None
        if href.startswith("/l/?") or "duckduckgo.com/l/?" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return href

    async def _fetch_page(self, url: str, full: bool = False) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        result: dict[str, Any] = {"title": title, "url": str(response.url), "text_preview": "\n".join(lines[:80])}
        if full:
            headings: list[dict[str, Any]] = []
            for tag in soup.find_all(["h1", "h2", "h3"]):
                headings.append({
                    "level": int(tag.name[1]),
                    "text": tag.get_text(strip=True),
                })
            result["headings"] = headings[:30]
        return result

    def _source_from_url(self, url: str) -> str:
        try:
            host = httpx.URL(url).host.lower()
            return host.replace("www.", "")
        except Exception:  # noqa: BLE001
            return "unknown"

    def _extract_game_headings(self, findings: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for f in findings:
            if not isinstance(f, dict):
                continue
            page_data = f.get("page_data") or {}
            for heading in page_data.get("headings", []):
                if isinstance(heading, dict):
                    level = heading.get("level", 2)
                    h = heading.get("text", "").strip()
                else:
                    level = 2
                    h = str(heading).strip()
                # Skip page titles (h1) and list headings like "Top 10 Games".
                if level == 1:
                    continue
                lower_h = h.lower()
                if "top " in lower_h and "games" in lower_h:
                    continue
                if "roblox games" in lower_h and "play" in lower_h:
                    continue
                if self._looks_like_game(h):
                    title = re.sub(r"^\d+\.\s*", "", h)
                    title = re.split(r"[–—\-:]", title)[0].strip()
                    key = title.lower()
                    if key not in seen:
                        seen.add(key)
                        names.append(title)
        return names

    def _looks_like_game(self, text: str) -> bool:
        """Heuristic: does this heading contain a game title?"""
        if not text:
            return False
        # Strip leading numbers like "1. " or "10. "
        text = re.sub(r"^\d+\.\s*", "", text).strip()
        # Split on em/en dash and take the first part as the title.
        title = re.split(r"[–—\-:]", text)[0].strip()
        if not title or len(title) > 60:
            return False
        words = title.split()
        if len(words) < 1 or len(words) > 8:
            return False
        lower = title.lower()
        generic = {
            "upcoming games", "best games", "top games", "new games", "release date",
            "guide", "review", "trailer", "gameplay", "news", "article", "more",
            "this week", "this month", "all", "honourable mentions", "conclusion",
            "introduction", "summary", "contents", "faq", "frequently asked",
        }
        for g in generic:
            if g in lower:
                return False
        if not re.match(r"^[A-Za-z0-9\s'.!?]+$", title):
            return False
        return True

    def _extract_genres(self, findings: list[dict[str, Any]]) -> list[str]:
        genre_words = [
            "roguelike", "roguelite", "survival", "horror", "rpg", "action",
            "adventure", "puzzle", "strategy", "simulation", "sports", "racing",
            "platformer", "shooter", "fps", "moba", "battle royale", "sandbox",
            "open world", "co-op", "multiplayer", "indie", "casual", "mmorpg",
        ]
        counts: dict[str, int] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            text = ""
            text += f.get("snippet", "") + " "
            text += (f.get("page_data") or {}).get("text_preview", "") + " "
            headings = (f.get("page_data") or {}).get("headings", [])
            for h in headings:
                if isinstance(h, dict):
                    text += " " + h.get("text", "")
                else:
                    text += " " + str(h)
            lower = text.lower()
            for genre in genre_words:
                counts[genre] = counts.get(genre, 0) + lower.count(genre)
        sorted_genres = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [g for g, c in sorted_genres if c > 0][:5]
