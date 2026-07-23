"""Shopify store automation skill.

Creates stores, adds products, configures themes, and builds pages via the
Shopify Admin REST API. Dry-run mode is the default so you can inspect every
action before spending money or touching a live store.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from jarvis_os.skills.base import Skill
from jarvis_os.skills.credentials import CredentialsSkill

logger = logging.getLogger(__name__)


SHOPIFY_API_VERSION = "2024-01"

_PLACEHOLDER_TOKENS = {
    "", "not_provided", "user_provided", "user_provided_access_token",
    "placeholder", "your_token", "your_access_token", "<token>", "<access_token>",
}


def _looks_real(token: str) -> bool:
    """Reject common agent-hallucinated placeholders."""
    if not token or token.strip().lower() in _PLACEHOLDER_TOKENS:
        return False
    return True


async def _resolve_token(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Return {'access_token': ...} or a needs_auth dict."""
    token: str | None = None
    if kwargs.get("access_token"):
        token = kwargs["access_token"]
    elif kwargs.get("api_password"):
        token = kwargs["api_password"]
    elif kwargs.get("api_key") and kwargs.get("api_password"):
        token = kwargs["api_password"]

    if token and _looks_real(token):
        return {"access_token": token}

    stored = await CredentialsSkill().run(action="get", provider="shopify")
    if stored and stored.get("found"):
        return {"access_token": stored["value"]}

    return await CredentialsSkill().run(
        action="request_auth",
        provider="shopify",
        auth_url="https://partners.shopify.com/organizations",
        instructions=(
            "1. Open Shopify Partners and log in.\n"
            "2. Create a development store (or open an existing store).\n"
            "3. In the store admin, go to Settings > Apps and sales channels > "
            "Develop apps.\n"
            "4. Create an app, enable Admin API access, and generate an "
            "Admin API access token.\n"
            "5. Paste the token and your store URL below."
        ),
        extra_fields=[
            {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
        ],
    )


async def _handle_auth_failure() -> dict[str, Any]:
    """Clear bad stored token and ask the user to log in again."""
    await CredentialsSkill().run(action="delete", provider="shopify")
    return await CredentialsSkill().run(
        action="request_auth",
        provider="shopify",
        auth_url="https://partners.shopify.com/organizations",
        instructions=(
            "The stored Shopify access token was rejected (401 Unauthorized).\n"
            "1. Open Shopify Partners and log in.\n"
            "2. Create or open a development store.\n"
            "3. In the store admin, go to Settings > Apps and sales channels > "
            "Develop apps.\n"
            "4. Create an app, enable Admin API access, and generate an "
            "Admin API access token.\n"
            "5. Paste the new token and your store URL below."
        ),
        extra_fields=[
            {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
        ],
    )


class ShopifySkill(Skill):
    """Automate Shopify store setup and product management."""

    name = "shopify"
    description = (
        "Create and manage Shopify stores: create dev stores, add products, "
        "configure themes, create pages, and publish collections via the Shopify Admin API."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_store",
                    "get_store",
                    "add_product",
                    "create_page",
                    "create_collection",
                    "configure_theme",
                ],
                "description": "Shopify action to perform.",
            },
            "store_url": {
                "type": "string",
                "description": "Shopify store URL, e.g. https://your-store.myshopify.com",
            },
            "access_token": {
                "type": "string",
                "description": "Shopify Admin API access token.",
            },
            "api_key": {
                "type": "string",
                "description": "Shopify API key (for private apps / custom apps).",
            },
            "api_password": {
                "type": "string",
                "description": "Shopify API password / admin access token.",
            },
            "store_name": {
                "type": "string",
                "description": "Human-readable store name for create_store.",
            },
            "email": {
                "type": "string",
                "description": "Store owner email for create_store.",
            },
            "product": {
                "type": "object",
                "description": "Product payload for add_product (title, body_html, vendor, product_type, variants, images).",
            },
            "page": {
                "type": "object",
                "description": "Page payload for create_page (title, body_html, handle optional).",
            },
            "collection": {
                "type": "object",
                "description": "Collection payload for create_collection (title, body_html, products).",
            },
            "theme_settings": {
                "type": "object",
                "description": "Theme settings to apply for configure_theme.",
            },
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "If true, return the planned API call without executing it.",
            },
        },
        "required": ["action"],
    }
    permissions = ["shopify:write", "shopify:read"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "create_store":
            return await self._create_store(kwargs)
        if action == "get_store":
            return await self._get_store(kwargs)
        if action == "add_product":
            return await self._add_product(kwargs)
        if action == "create_page":
            return await self._create_page(kwargs)
        if action == "create_collection":
            return await self._create_collection(kwargs)
        if action == "configure_theme":
            return await self._configure_theme(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _credentials(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        """Extract credentials from kwargs or vault; return needs_auth if missing."""
        return await _resolve_token(kwargs)

    def _headers(self, creds: dict[str, str]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if "access_token" in creds:
            headers["X-Shopify-Access-Token"] = creds["access_token"]
        return headers

    def _base_url(self, store_url: str) -> str:
        store_url = store_url.rstrip("/")
        if not store_url.startswith(("http://", "https://")):
            store_url = f"https://{store_url}"
        return f"{store_url}/admin/api/{SHOPIFY_API_VERSION}"

    async def _resolve_store_url(self, kwargs: dict[str, Any]) -> str | None:
        """Return store_url from kwargs or the encrypted vault."""
        store_url = kwargs.get("store_url", "")
        if store_url:
            return store_url
        stored = await CredentialsSkill().run(action="get", provider="shopify_store_url")
        if stored and stored.get("found"):
            return stored["value"]
        return None

    async def _create_store(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Create a Shopify store.

        Real automated store creation requires the Shopify Partner API and a
        Partner organization. Most users will create the store manually in the
        Partner dashboard, then pass store_url + access_token to the other actions.
        This skill returns the exact Partner API payload you would send.
        """
        store_name = kwargs.get("store_name", "My Jarvis Store")
        email = kwargs.get("email", "owner@example.com")
        dry_run = kwargs.get("dry_run", True)

        payload = {
            "store": {
                "name": store_name,
                "email": email,
                "domain": None,  # Shopify assigns myshopify.com domain
                "plan_name": "partner_test",  # dev store
            }
        }

        if dry_run:
            return {
                "action": "create_store",
                "dry_run": True,
                "note": (
                    "Automated store creation requires a Shopify Partner API token. "
                    "Create a Shopify Partner account, then either use the Partner API "
                    "or create the dev store manually and supply store_url + access_token."
                ),
                "partner_api_endpoint": "POST https://partners.shopify.com/api/2024-01/stores.json",
                "payload": payload,
                "next_step": "Pass store_url and access_token to add_product / create_page.",
            }

        # Live path requires partner_token, not implemented by default.
        return {
            "error": (
                "Live store creation requires Shopify Partner API credentials. "
                "Create the store manually, then use store_url + access_token for live actions."
            )
        }

    async def _get_store(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        creds = await self._credentials(kwargs)
        if creds is None or not creds.get("access_token"):
            return creds or {"error": "access_token or api_password is required for get_store"}
        store_url = await self._resolve_store_url(kwargs)
        if not store_url:
            return await CredentialsSkill().run(
                action="request_auth",
                provider="shopify",
                auth_url="https://partners.shopify.com/organizations",
                instructions="Shopify access token is stored, but the store URL is missing. Please provide your store URL.",
                extra_fields=[
                    {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
                ],
            )

        url = f"{self._base_url(store_url)}/shop.json"
        if kwargs.get("dry_run", True):
            return {"action": "get_store", "dry_run": True, "method": "GET", "url": url}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=self._headers(creds))
                response.raise_for_status()
                return {"action": "get_store", "shop": response.json().get("shop", {})}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Failed to get store: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to get store: {exc}"}

    async def _add_product(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        store_url = await self._resolve_store_url(kwargs)
        product = kwargs.get("product", {})
        if not store_url:
            return await CredentialsSkill().run(
                action="request_auth",
                provider="shopify",
                auth_url="https://partners.shopify.com/organizations",
                instructions="Shopify store URL is missing. Please provide your store URL (and access token if not already stored).",
                extra_fields=[
                    {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
                ],
            )
        if not product:
            return {"error": "product payload is required for add_product"}
        creds = await self._credentials(kwargs)
        if creds is None or not creds.get("access_token"):
            return creds or {"error": "access_token or api_password is required for add_product"}

        url = f"{self._base_url(store_url)}/products.json"
        payload = {"product": product}

        if kwargs.get("dry_run", True):
            return {
                "action": "add_product",
                "dry_run": True,
                "method": "POST",
                "url": url,
                "payload": payload,
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=self._headers(creds), json=payload)
                response.raise_for_status()
                return {"action": "add_product", "product": response.json().get("product", {})}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Failed to add product: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to add product: {exc}"}

    async def _create_page(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        store_url = await self._resolve_store_url(kwargs)
        page = kwargs.get("page", {})
        if not store_url:
            return await CredentialsSkill().run(
                action="request_auth",
                provider="shopify",
                auth_url="https://partners.shopify.com/organizations",
                instructions="Shopify store URL is missing. Please provide your store URL (and access token if not already stored).",
                extra_fields=[
                    {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
                ],
            )
        if not page:
            return {"error": "page payload is required for create_page"}
        creds = await self._credentials(kwargs)
        if creds is None or not creds.get("access_token"):
            return creds or {"error": "access_token or api_password is required for create_page"}

        url = f"{self._base_url(store_url)}/pages.json"
        payload = {"page": page}

        if kwargs.get("dry_run", True):
            return {
                "action": "create_page",
                "dry_run": True,
                "method": "POST",
                "url": url,
                "payload": payload,
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=self._headers(creds), json=payload)
                response.raise_for_status()
                return {"action": "create_page", "page": response.json().get("page", {})}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Failed to create page: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to create page: {exc}"}

    async def _create_collection(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        store_url = await self._resolve_store_url(kwargs)
        collection = kwargs.get("collection", {})
        if not store_url:
            return await CredentialsSkill().run(
                action="request_auth",
                provider="shopify",
                auth_url="https://partners.shopify.com/organizations",
                instructions="Shopify store URL is missing. Please provide your store URL (and access token if not already stored).",
                extra_fields=[
                    {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
                ],
            )
        if not collection:
            return {"error": "collection payload is required for create_collection"}
        creds = await self._credentials(kwargs)
        if creds is None or not creds.get("access_token"):
            return creds or {"error": "access_token or api_password is required for create_collection"}

        url = f"{self._base_url(store_url)}/custom_collections.json"
        payload = {"custom_collection": collection}

        if kwargs.get("dry_run", True):
            return {
                "action": "create_collection",
                "dry_run": True,
                "method": "POST",
                "url": url,
                "payload": payload,
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=self._headers(creds), json=payload)
                response.raise_for_status()
                return {"action": "create_collection", "collection": response.json().get("custom_collection", {})}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Failed to create collection: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to create collection: {exc}"}

    async def _configure_theme(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        creds = await self._credentials(kwargs)
        if creds is None or not creds.get("access_token"):
            return creds or {"error": "access_token or api_password is required for configure_theme"}
        store_url = await self._resolve_store_url(kwargs)
        theme_settings = kwargs.get("theme_settings", {})
        if not store_url:
            return await CredentialsSkill().run(
                action="request_auth",
                provider="shopify",
                auth_url="https://partners.shopify.com/organizations",
                instructions="Shopify access token is stored, but the store URL is missing. Please provide your store URL.",
                extra_fields=[
                    {"name": "store_url", "label": "Shopify store URL (e.g. https://your-store.myshopify.com)"},
                ],
            )

        # First list themes to find the active/main theme.
        list_url = f"{self._base_url(store_url)}/themes.json"
        if kwargs.get("dry_run", True):
            return {
                "action": "configure_theme",
                "dry_run": True,
                "steps": [
                    {"method": "GET", "url": list_url, "purpose": "Find main theme id"},
                    {
                        "method": "PUT",
                        "url": f"{self._base_url(store_url)}/themes/{{theme_id}}/assets.json",
                        "purpose": "Update theme asset (e.g. config/settings_data.json)",
                        "payload": {"asset": {"key": "config/settings_data.json", "value": json_value(theme_settings)}},
                    },
                ],
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                list_response = await client.get(list_url, headers=self._headers(creds))
                list_response.raise_for_status()
                themes = list_response.json().get("themes", [])
                main_theme = next((t for t in themes if t.get("role") == "main"), themes[0] if themes else None)
                if not main_theme:
                    return {"error": "No theme found in store"}

                theme_id = main_theme["id"]
                asset_url = f"{self._base_url(store_url)}/themes/{theme_id}/assets.json"
                payload = {
                    "asset": {
                        "key": "config/settings_data.json",
                        "value": json_value(theme_settings),
                    }
                }
                response = await client.put(asset_url, headers=self._headers(creds), json=payload)
                response.raise_for_status()
                return {"action": "configure_theme", "theme_id": theme_id, "asset": response.json().get("asset", {})}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Failed to configure theme: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to configure theme: {exc}"}


def json_value(value: Any) -> str:
    """Serialize dict to JSON string for Shopify theme asset value."""
    import json
    if isinstance(value, str):
        return value
    return json.dumps(value)
