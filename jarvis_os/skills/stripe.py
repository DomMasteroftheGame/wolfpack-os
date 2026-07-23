"""Stripe payment processing skill.

Creates Stripe products, prices, payment links, and customer portal configs
via the Stripe API. Dry-run by default.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from jarvis_os.skills.base import Skill
from jarvis_os.skills.credentials import CredentialsSkill

logger = logging.getLogger(__name__)

STRIPE_API_VERSION = "2024-06-20"

_PLACEHOLDER_KEYS = {
    "", "not_provided", "user_provided", "user_provided_api_key",
    "placeholder", "your_key", "your_api_key", "<key>", "<api_key>",
}


def _looks_real(key: str) -> bool:
    if not key or key.strip().lower() in _PLACEHOLDER_KEYS:
        return False
    return True


async def _resolve_key(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Return {'api_key': ...} or a needs_auth dict."""
    api_key = kwargs.get("api_key", "")
    if _looks_real(api_key):
        return {"api_key": api_key}

    stored = await CredentialsSkill().run(action="get", provider="stripe")
    if stored and stored.get("found"):
        return {"api_key": stored["value"]}

    return await CredentialsSkill().run(
        action="request_auth",
        provider="stripe",
        auth_url="https://dashboard.stripe.com/apikeys",
        instructions=(
            "1. Open the Stripe Dashboard and log in.\n"
            "2. Go to Developers > API keys.\n"
            "3. Reveal the Secret key (sk_...).\n"
            "4. Paste it below."
        ),
    )


async def _handle_auth_failure() -> dict[str, Any]:
    await CredentialsSkill().run(action="delete", provider="stripe")
    return await CredentialsSkill().run(
        action="request_auth",
        provider="stripe",
        auth_url="https://dashboard.stripe.com/apikeys",
        instructions=(
            "The stored Stripe secret key was rejected.\n"
            "1. Open the Stripe Dashboard and log in.\n"
            "2. Go to Developers > API keys.\n"
            "3. Reveal the Secret key (sk_...).\n"
            "4. Paste the new key below."
        ),
    )


class StripeSkill(Skill):
    """Automate Stripe account setup and payment operations."""

    name = "stripe"
    description = (
        "Create Stripe products, prices, payment links, coupons, and customer "
        "portal configurations via the Stripe API."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_product", "create_price", "create_payment_link", "create_coupon"],
                "description": "Stripe action to perform.",
            },
            "api_key": {
                "type": "string",
                "description": "Stripe secret API key (sk_...).",
            },
            "product": {
                "type": "object",
                "description": "Product payload for create_product (name, description, images).",
            },
            "price": {
                "type": "object",
                "description": "Price payload for create_price (unit_amount, currency, product).",
            },
            "payment_link": {
                "type": "object",
                "description": "Payment link payload for create_payment_link (line_items).",
            },
            "coupon": {
                "type": "object",
                "description": "Coupon payload for create_coupon (percent_off, duration).",
            },
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "If true, return planned API calls without executing.",
            },
        },
        "required": ["action"],
    }
    permissions = ["stripe:write", "stripe:read"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "create_product":
            return await self._create_product(kwargs)
        if action == "create_price":
            return await self._create_price(kwargs)
        if action == "create_payment_link":
            return await self._create_payment_link(kwargs)
        if action == "create_coupon":
            return await self._create_coupon(kwargs)
        return {"error": f"Unknown action: {action}"}

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": STRIPE_API_VERSION,
        }

    async def _post(self, api_key: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.stripe.com/v1{path}",
                headers=self._headers(api_key),
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def _create_product(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        product = kwargs.get("product", {})
        if not product:
            return {"error": "product payload is required for create_product"}
        if kwargs.get("dry_run", True):
            return {
                "action": "create_product",
                "dry_run": True,
                "endpoint": "POST https://api.stripe.com/v1/products",
                "payload": product,
            }
        creds = await _resolve_key(kwargs)
        if creds is None or not creds.get("api_key"):
            return creds or {"error": "api_key is required for live Stripe actions"}
        try:
            result = await self._post(creds["api_key"], "/products", product)
            return {"action": "create_product", "product": result}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Stripe create_product failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Stripe create_product failed: {exc}"}

    async def _create_price(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        price = kwargs.get("price", {})
        if not price:
            return {"error": "price payload is required for create_price"}
        if kwargs.get("dry_run", True):
            return {
                "action": "create_price",
                "dry_run": True,
                "endpoint": "POST https://api.stripe.com/v1/prices",
                "payload": price,
            }
        creds = await _resolve_key(kwargs)
        if creds is None or not creds.get("api_key"):
            return creds or {"error": "api_key is required for live Stripe actions"}
        try:
            result = await self._post(creds["api_key"], "/prices", price)
            return {"action": "create_price", "price": result}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Stripe create_price failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Stripe create_price failed: {exc}"}

    async def _create_payment_link(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        link = kwargs.get("payment_link", {})
        if not link:
            return {"error": "payment_link payload is required for create_payment_link"}
        if kwargs.get("dry_run", True):
            return {
                "action": "create_payment_link",
                "dry_run": True,
                "endpoint": "POST https://api.stripe.com/v1/payment_links",
                "payload": link,
            }
        creds = await _resolve_key(kwargs)
        if creds is None or not creds.get("api_key"):
            return creds or {"error": "api_key is required for live Stripe actions"}
        try:
            result = await self._post(creds["api_key"], "/payment_links", link)
            return {"action": "create_payment_link", "payment_link": result}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Stripe create_payment_link failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Stripe create_payment_link failed: {exc}"}

    async def _create_coupon(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        coupon = kwargs.get("coupon", {})
        if not coupon:
            return {"error": "coupon payload is required for create_coupon"}
        if kwargs.get("dry_run", True):
            return {
                "action": "create_coupon",
                "dry_run": True,
                "endpoint": "POST https://api.stripe.com/v1/coupons",
                "payload": coupon,
            }
        creds = await _resolve_key(kwargs)
        if creds is None or not creds.get("api_key"):
            return creds or {"error": "api_key is required for live Stripe actions"}
        try:
            result = await self._post(creds["api_key"], "/coupons", coupon)
            return {"action": "create_coupon", "coupon": result}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return await _handle_auth_failure()
            return {"error": f"Stripe create_coupon failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Stripe create_coupon failed: {exc}"}
