"""Business launch orchestrator.

Chains research, concept generation, domain check, Shopify prep, Stripe prep,
logo prompts, email setup, and social media planning into one skill.
"""

from __future__ import annotations

import logging
from typing import Any

from jarvis_os.skills.base import Skill
from jarvis_os.skills.domain import DomainSkill
from jarvis_os.skills.dropship_research import DropshipResearchSkill
from jarvis_os.skills.email_setup import EmailSetupSkill
from jarvis_os.skills.logo_design import LogoDesignSkill
from jarvis_os.skills.shopify import ShopifySkill
from jarvis_os.skills.social_media import SocialMediaSkill
from jarvis_os.skills.stripe import StripeSkill

logger = logging.getLogger(__name__)


class BusinessLaunchSkill(Skill):
    """Orchestrate a full dropshipping/ecommerce business launch plan."""

    name = "business_launch"
    description = (
        "Use this tool when the user wants to launch a business, start a store, "
        "create a dropshipping store, or build an ecommerce brand. It researches "
        "products, generates a store concept, finds domains, prepares Shopify, "
        "Stripe, logo, email, and social media setup — all in one call."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["launch_dropshipping_store"],
                "description": "Business launch action.",
            },
            "niche": {
                "type": "string",
                "description": "Optional niche to research. If omitted, trending products are researched.",
            },
            "store_name": {
                "type": "string",
                "description": "Preferred store name. If omitted, one is generated from research.",
            },
            "email_provider": {
                "type": "string",
                "enum": ["google_workspace", "zoho_mail", "microsoft_365"],
                "default": "google_workspace",
            },
            "live": {
                "type": "boolean",
                "default": False,
                "description": "If true, execute Shopify and Stripe actions live (requires stored credentials).",
            },
        },
        "required": ["action"],
    }
    permissions = ["business:plan"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "launch_dropshipping_store":
            return await self._launch_dropshipping(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _launch_dropshipping(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        niche = kwargs.get("niche", "")
        store_name = kwargs.get("store_name", "")
        email_provider = kwargs.get("email_provider", "google_workspace")
        live = kwargs.get("live", False)

        # 1. Research products.
        research = DropshipResearchSkill()
        if niche:
            research_result = await research.run(action="research_niche", niche=niche, max_results=6)
            findings = research_result.get("results", [])
            if not findings:
                research_result = await research.run(action="find_trending", max_results=6)
                findings = research_result.get("results", [])
        else:
            research_result = await research.run(action="find_trending", max_results=6)
            findings = research_result.get("results", [])

        # 2. Generate store concept.
        if findings:
            concept_result = await research.run(action="generate_concept", findings=findings)
            concept = concept_result.get("concept", {})
        else:
            concept = {}

        # Use generated name if store_name not provided.
        if not store_name:
            suggestions = concept.get("store_name_suggestions", [])
            store_name = suggestions[0] if suggestions else "MyStore"

        # 3. Domain suggestions.
        domain = DomainSkill()
        domain_result = await domain.run(action="suggest_domains", name=store_name)
        available_domains = [d for d in domain_result.get("suggestions", []) if d.get("available")]
        chosen_domain = available_domains[0]["domain"] if available_domains else None

        # 4. Shopify store plan.
        shopify = ShopifySkill()
        shopify_result = await shopify.run(
            action="create_store",
            store_name=store_name,
            email=f"info@{chosen_domain}" if chosen_domain else "owner@example.com",
            dry_run=not live,
        )

        # 5. Stripe product/price plan for first product.
        target_products = concept.get("target_products", [])
        first_product = target_products[0] if target_products else {"name": "Signature Product"}
        stripe = StripeSkill()
        stripe_product = await stripe.run(
            action="create_product",
            product={"name": first_product.get("name", "Signature Product"), "description": first_product.get("notes", "")},
            dry_run=not live,
        )
        stripe_price = await stripe.run(
            action="create_price",
            price={"unit_amount": 1997, "currency": "usd", "product": "prod_placeholder"},
            dry_run=not live,
        )

        # 6. Logo prompts.
        logo = LogoDesignSkill()
        logo_result = await logo.run(action="generate_prompts", brand_name=store_name, niche=concept.get("niche", "ecommerce"))

        # 7. Email setup plan.
        email = EmailSetupSkill()
        email_result = await email.run(
            action="plan_setup",
            provider=email_provider,
            domain=chosen_domain or "example.com",
            users=[{"name": "Owner", "email_alias": "hello"}],
        )

        # 8. Social media plan.
        social = SocialMediaSkill()
        social_result = await social.run(
            action="generate_presence",
            brand_name=store_name,
            niche=concept.get("niche", "ecommerce"),
        )

        return {
            "action": "launch_dropshipping_store",
            "store_name": store_name,
            "chosen_domain": chosen_domain,
            "concept": concept,
            "domain_suggestions": domain_result.get("suggestions", []),
            "shopify_plan": shopify_result,
            "stripe_plan": {"product": stripe_product, "price": stripe_price},
            "logo_prompts": logo_result.get("prompts", {}),
            "email_plan": email_result,
            "social_plan": social_result.get("profiles", {}),
            "launch_checklist": [
                "Buy the chosen domain",
                "Create Shopify dev store and connect domain",
                "Connect Stripe account and create real products/prices",
                "Generate logo using one of the prompts",
                "Set up business email",
                "Create social media accounts",
                "Add products to Shopify",
                "Launch store",
            ],
        }
