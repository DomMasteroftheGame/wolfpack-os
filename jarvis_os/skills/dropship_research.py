"""Dropshipping product research skill.

Finds trending products, analyzes listings, and generates store concepts
with little human input. Uses web search + page fetching; does not require
paid APIs for the research phase.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

# Search queries that surface winning products.
_TRENDING_QUERIES = [
    "best selling dropshipping products 2025",
    "top trending products aliexpress 2025",
    "tiktok viral products dropshipping",
    "winning products dropshipping reddit",
    "high demand low competition dropshipping",
]

# Sites we prefer to fetch for product data.
_PREFERRED_SOURCES = [
    "aliexpress.com",
    "cjdropshipping.com",
    "alibaba.com",
    "amazon.com",
    "etsy.com",
]

# Fallback pages known to list dropshipping product ideas. Used when DDG blocks us.
_FALLBACK_SOURCES: list[dict[str, str]] = [
    {
        "url": "https://www.oberlo.com/blog/best-dropshipping-products",
        "title": "Oberlo: Best Dropshipping Products",
    },
    {
        "url": "https://www.shopify.com/blog/best-dropshipping-products",
        "title": "Shopify: Best Dropshipping Products",
    },
    {
        "url": "https://www.salehoo.com/blog/dropshipping-products",
        "title": "SaleHoo: Dropshipping Products",
    },
    {
        "url": "https://www.aliexpress.com/popular.html",
        "title": "AliExpress Popular Products",
    },
    {
        "url": "https://cjdropshipping.com/product.html",
        "title": "CJ Dropshipping Products",
    },
]


class DropshipResearchSkill(Skill):
    """Research winning dropshipping products and turn findings into a store concept."""

    name = "dropship_research"
    description = (
        "Research trending dropshipping products, analyze competitor listings, "
        "and generate a complete store concept (niche, products, pricing, angles)."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "find_trending",
                    "research_niche",
                    "analyze_product",
                    "generate_concept",
                ],
                "description": "Research action to perform.",
            },
            "niche": {
                "type": "string",
                "description": "Specific niche to research (e.g. 'portable blenders').",
            },
            "url": {
                "type": "string",
                "description": "Product page URL to analyze.",
            },
            "findings": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Prior research findings to synthesize into a store concept.",
            },
            "max_results": {
                "type": "integer",
                "default": 8,
                "description": "Maximum search results to return.",
            },
        },
        "required": ["action"],
    }
    permissions = ["browser:search", "browser:fetch"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "find_trending":
            return await self._find_trending(kwargs)
        if action == "research_niche":
            return await self._research_niche(kwargs)
        if action == "analyze_product":
            return await self._analyze_product(kwargs)
        if action == "generate_concept":
            return await self._generate_concept(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _find_trending(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Search the web for multiple winning-product angles and return combined results."""
        max_results = kwargs.get("max_results", 8)
        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for query in _TRENDING_QUERIES:
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

        # Prioritize product-source URLs.
        all_results.sort(
            key=lambda x: (0 if x["source"] in _PREFERRED_SOURCES else 1, x["source"])
        )

        # Fetch a few top listings for richer data.
        fetched = await asyncio.gather(*[
            self._fetch_product_page(r["url"]) for r in all_results[:5]
        ])
        for r, data in zip(all_results[:5], fetched):
            r["page_data"] = data

        # If DDG returned nothing (blocked/rate-limited), fall back to known sources.
        if not all_results:
            logger.warning("DDG returned no results; using fallback dropshipping sources.")
            for src in _FALLBACK_SOURCES:
                all_results.append({
                    "title": src["title"],
                    "url": src["url"],
                    "snippet": "Fallback source for dropshipping product ideas.",
                    "source": self._source_from_url(src["url"]),
                    "page_data": await self._fetch_product_page(src["url"], full=True),
                })

        return {
            "action": "find_trending",
            "query_count": len(_TRENDING_QUERIES),
            "result_count": len(all_results),
            "results": all_results,
        }

    async def _research_niche(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Deep-dive a specific niche: products, price points, angles, competitors."""
        niche = kwargs.get("niche", "")
        if not niche:
            return {"error": "niche is required for research_niche"}
        max_results = kwargs.get("max_results", 8)

        queries = [
            f"best {niche} dropshipping suppliers",
            f"top {niche} products aliexpress",
            f"{niche} dropshipping profit margin",
            f"{niche} trending tiktok products",
        ]

        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for query in queries:
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

        # Fetch top results for structured data.
        fetched = await asyncio.gather(*[
            self._fetch_product_page(r["url"]) for r in all_results[:5]
        ])
        for r, data in zip(all_results[:5], fetched):
            r["page_data"] = data

        return {
            "action": "research_niche",
            "niche": niche,
            "query_count": len(queries),
            "result_count": len(all_results),
            "results": all_results,
        }

    async def _analyze_product(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Fetch a product page and extract structured listing information."""
        url = kwargs.get("url", "")
        if not url:
            return {"error": "url is required for analyze_product"}
        data = await self._fetch_product_page(url, full=True)
        return {
            "action": "analyze_product",
            "url": url,
            "source": self._source_from_url(url),
            **data,
        }

    async def _generate_concept(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Synthesize prior findings into a store concept the agent can execute.

        This intentionally returns a structured template rather than calling an LLM,
        so the agent's own planner can fill in the creative details.
        """
        findings = kwargs.get("findings", [])
        if not findings:
            return {"error": "findings are required for generate_concept"}

        # Extract concrete product names from page headings when available.
        product_names = self._extract_product_headings(findings)

        # Fall back to page/article titles if no product headings were found.
        titles: list[str] = []
        for f in findings:
            if isinstance(f, dict):
                title = f.get("title") or (f.get("page_data") or {}).get("title")
                if title:
                    titles.append(title)

        if not product_names:
            product_names = [t.split(" - ")[0].split(" | ")[0] for t in titles[:5]]

        target_products = [
            {
                "name": name,
                "source_url": findings[i % len(findings)].get("url") if findings else None,
                "supplier": findings[i % len(findings)].get("source") if findings else None,
                "notes": "Winning product idea from research.",
            }
            for i, name in enumerate(product_names[:8])
        ]

        concept = {
            "niche": self._infer_niche(product_names) if product_names else "General dropshipping",
            "store_name_suggestions": self._suggest_store_names(product_names or titles),
            "tagline_angle": self._infer_angle(product_names or titles),
            "target_products": target_products,
            "pricing_strategy": "3-5x cost-plus-shipping with psychological thresholds ($19.97, $29.97, $39.97)",
            "recommended_pages": [
                {"title": "About Us", "purpose": "Founder story / mission"},
                {"title": "Shipping & Delivery", "purpose": "Set expectations (7-15 days typical for dropshipping)"},
                {"title": "Returns & Refunds", "purpose": "Policy to reduce chargebacks"},
                {"title": "Contact Us", "purpose": "Support email / form"},
                {"title": "FAQ", "purpose": "Answer common objections"},
            ],
            "marketing_angles": [
                "Problem-solution video ad hook",
                "Before/after user-generated content",
                "Limited-time scarcity offer",
            ],
            "next_steps": [
                "Choose store name and buy domain",
                "Create Shopify store",
                "Add 1-3 winning products with descriptions",
                "Configure payment provider",
                "Create ad creative / landing page",
            ],
        }

        return {
            "action": "generate_concept",
            "concept": concept,
            "based_on_findings": len(findings),
        }

    async def _ddg_search(self, query: str, max_results: int = 8) -> list[dict[str, str]]:
        """Direct DuckDuckGo HTML search; does not rely on the renamed ddgs package."""
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
            # DDG HTML wraps results in a redirect URL; try to extract the real URL.
            real_url = self._extract_real_url(href)
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            results.append({
                "title": title,
                "url": real_url or href,
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break
        return results

    def _extract_real_url(self, href: str) -> str | None:
        """DuckDuckGo HTML sometimes returns /l/?uddg=... redirect URLs."""
        from urllib.parse import unquote, urlparse, parse_qs

        if not href:
            return None
        if href.startswith("/l/?") or "duckduckgo.com/l/?" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return href

    async def _fetch_product_page(self, url: str, full: bool = False) -> dict[str, Any]:
        """Fetch and lightly parse a product/supplier page."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(url, headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                })
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else None

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        result: dict[str, Any] = {
            "title": title,
            "url": str(response.url),
            "text_preview": "\n".join(lines[:80]),
        }

        if full:
            # Try to extract price-like strings and image URLs.
            prices = re.findall(r"\$\d{1,4}(?:\.\d{2})?", " ".join(lines))
            images: list[str] = []
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src and isinstance(src, str):
                    if src.startswith("//"):
                        src = "https:" + src
                    if src.startswith("http"):
                        images.append(src)
            result["prices_found"] = list(dict.fromkeys(prices))[:10]
            result["image_urls"] = images[:10]
            result["headings"] = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:20]

        return result

    def _source_from_url(self, url: str) -> str:
        try:
            host = httpx.URL(url).host.lower()
            return host.replace("www.", "")
        except Exception:  # noqa: BLE001
            return "unknown"

    def _extract_product_headings(self, findings: list[dict[str, Any]]) -> list[str]:
        """Pull concrete product names out of h2/h3 headings from research pages."""
        headings: list[str] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            page_data = f.get("page_data") or {}
            for h in page_data.get("headings", []):
                h = h.strip()
                if self._looks_like_product(h):
                    headings.append(h)
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for h in headings:
            key = h.lower()
            if key not in seen:
                seen.add(key)
                unique.append(h)
        return unique

    def _looks_like_product(self, text: str) -> bool:
        """Heuristic: is this heading a product name, not a section title?"""
        if not text or len(text) > 60:
            return False
        words = text.split()
        if len(words) < 1 or len(words) > 6:
            return False

        lower = text.lower()
        generic = {
            "introduction", "conclusion", "summary", "contents", "using",
            "dropshipping", "business", "today", "learn more", "start your",
            "best", "products", "product", "ideas", "recommended", "contributing",
            "authors", "key takeaways", "quick picks", "article", "skip",
            "how to", "find products", "watch", "trends", "social", "shopping",
        }
        for g in generic:
            if g in lower:
                return False

        # Must be mostly alphanumeric / spaces.
        if not re.match(r"^[A-Za-z0-9\s\-'&]+$", text):
            return False
        return True

    def _infer_niche(self, product_names: list[str]) -> str:
        """Guess the niche from the extracted product names."""
        text = " ".join(product_names).lower()
        if any(w in text for w in ["hoodie", "tote", "wallet", "watch", "necklace", "bag", "sock", "sweater", "apparel", "clothing"]):
            return "Fashion & accessories"
        if any(w in text for w in ["phone", "laptop", "charger", "case", "screen", "keyboard", "gadget"]):
            return "Tech accessories"
        if any(w in text for w in ["kitchen", "cooking", "home", "diffuser", "decor", "furniture"]):
            return "Home & kitchen"
        if any(w in text for w in ["beauty", "skin", "eyelash", "care", "makeup", "cosmetic"]):
            return "Beauty & personal care"
        if any(w in text for w in ["pet", "dog", "cat"]):
            return "Pet products"
        return "General dropshipping"

    def _suggest_store_names(self, titles: list[str]) -> list[str]:
        """Generate a few brand-name candidates from product titles."""
        words: set[str] = set()
        for t in titles:
            for word in re.findall(r"[A-Za-z]{4,}", t.lower()):
                if word not in {"dropshipping", "aliexpress", "amazon", "products", "review", "best", "cheap"}:
                    words.add(word)
        candidates: list[str] = []
        for w in list(words)[:6]:
            candidates.append(f"{w.capitalize()}Vault")
            candidates.append(f"{w.capitalize()}Hub")
        return candidates or ["TrendVault", "NicheHub", "DropMart"]

    def _infer_angle(self, titles: list[str]) -> str:
        """Infer a marketing angle from the most common words."""
        text = " ".join(titles).lower()
        if any(x in text for x in ["portable", "travel", "compact", "mini"]):
            return "Convenience on the go — solve everyday problems with compact, portable gear."
        if any(x in text for x in ["pet", "dog", "cat"]):
            return "Pamper their pet — emotional products for proud owners."
        if any(x in text for x in ["kitchen", "cooking", "home"]):
            return "Upgrade the home — practical gadgets that look premium."
        if any(x in text for x in ["beauty", "skin", "care"]):
            return "Self-care made simple — affordable beauty and wellness essentials."
        return "Everyday upgrades — useful products people didn't know they needed."
