"""AI-run business orchestrator.

Sets up and operates an autonomous business: creates the store, automates
operations, deploys a customer-service chatbot, and starts an analytics loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from jarvis_os.skills.ai_analyst import AIAnalystSkill
from jarvis_os.skills.ai_automation import AIAutomationSkill
from jarvis_os.skills.ai_chatbot import AIChatbotSkill
from jarvis_os.skills.base import Skill
from jarvis_os.skills.domain import DomainSkill
from jarvis_os.skills.dropship_research import DropshipResearchSkill
from jarvis_os.skills.shopify import ShopifySkill
from jarvis_os.skills.social_media import SocialMediaSkill
from jarvis_os.skills.stripe import StripeSkill

logger = logging.getLogger(__name__)


class AIRunBusinessSkill(Skill):
    """End-to-end AI-run business creation and operation."""

    name = "ai_run_business"
    description = (
        "Create and operate an AI-ran business from a single prompt: research, "
        "build store, automate operations, deploy customer service chatbot, and "
        "start analytics-driven improvement loop."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["launch", "operate", "report"],
                "description": "AI-run business action.",
            },
            "niche": {
                "type": "string",
                "description": "Business niche or product idea.",
            },
            "business_name": {
                "type": "string",
                "description": "Preferred business name.",
            },
            "platform": {
                "type": "string",
                "enum": ["shopify", "woocommerce", "gumroad", "stan_store"],
                "default": "shopify",
            },
            "budget": {
                "type": "number",
                "description": "Approximate launch budget in USD.",
            },
            "automation_level": {
                "type": "string",
                "enum": ["basic", "full"],
                "default": "basic",
                "description": "Level of AI automation to deploy.",
            },
            "execute": {
                "type": "boolean",
                "default": False,
                "description": "If true, actually run the research, domain, chatbot, automation, analyst, and social media skills instead of only returning a plan.",
            },
            "domain": {
                "type": "string",
                "description": "Target domain to purchase (e.g. example.com). If omitted, one will be suggested.",
            },
            "registrar": {
                "type": "string",
                "enum": ["cloudflare", "namecheap", "porkbun"],
                "default": "cloudflare",
                "description": "Domain registrar to use for live purchase.",
            },
        },
        "required": ["action"],
    }
    permissions = ["file:write", "network:read", "shopify:write", "stripe:write", "domain:purchase"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "launch":
            return await self._launch(kwargs)
        if action == "operate":
            return await self._operate(kwargs)
        if action == "report":
            return await self._report(kwargs)
        return {"error": f"Unknown action: {action}"}

    # ---------- persistence / resume helpers ----------

    def _slugify(self, name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower())[:30] or "business"

    def _state_path(self, slug: str) -> Path:
        base = Path(__file__).parent.parent.parent / "ai_businesses" / slug
        base.mkdir(parents=True, exist_ok=True)
        return base / "launch_state.json"

    def _load_state(self, slug: str) -> dict[str, Any]:
        path = self._state_path(slug)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save_state(self, slug: str, state: dict[str, Any]) -> None:
        path = self._state_path(slug)
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    async def _run_with_timeout(self, coro: Any, timeout: float = 30) -> Any:
        """Run a coroutine with a timeout so the GUI event loop never stalls forever."""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": f"Timed out after {timeout}s"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # ---------- launch orchestration ----------

    async def _launch(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        niche = kwargs.get("niche", "trending products")
        business_name = kwargs.get("business_name", f"AI {niche.title()} Store")
        platform = kwargs.get("platform", "shopify")
        budget = kwargs.get("budget", 500)
        automation_level = kwargs.get("automation_level", "basic")
        execute = kwargs.get("execute", False)
        domain_name = kwargs.get("domain")
        registrar = kwargs.get("registrar", "cloudflare")

        slug = self._slugify(business_name)
        state = self._load_state(slug)
        executed_results: dict[str, Any] = state.get("executed", {})
        live_results: dict[str, Any] = state.get("live", {})

        if execute:
            # 1. Shopify auth/setup (fast credential check; pauses GUI if missing).
            if "shopify" not in live_results:
                shopify_res = await self._setup_shopify(business_name, kwargs)
                if shopify_res.get("needs_auth"):
                    return shopify_res
                live_results["shopify"] = shopify_res
                state["live"] = live_results
                self._save_state(slug, state)

            # 2. Stripe auth/setup.
            if "stripe" not in live_results:
                stripe_res = await self._setup_stripe(business_name, kwargs)
                if stripe_res.get("needs_auth"):
                    return stripe_res
                live_results["stripe"] = stripe_res
                state["live"] = live_results
                self._save_state(slug, state)

            # 3. Domain auth/setup.
            if "domain" not in live_results:
                domain_res = await self._setup_domain(business_name, kwargs, domain_name, registrar)
                if domain_res.get("needs_auth"):
                    return domain_res
                live_results["domain"] = domain_res
                state["live"] = live_results
                self._save_state(slug, state)

            # 4. Asset-generation skills (with timeouts so research can't freeze the GUI).
            if "research" not in executed_results:
                executed_results["research"] = await self._run_with_timeout(
                    DropshipResearchSkill().run(action="find_trending", niche=niche),
                    timeout=45,
                )
            research_findings = executed_results.get("research", {}).get("results", [])

            if "concept" not in executed_results:
                executed_results["concept"] = await self._run_with_timeout(
                    DropshipResearchSkill().run(action="generate_concept", findings=research_findings),
                    timeout=20,
                )

            if "domains" not in executed_results:
                executed_results["domains"] = await self._run_with_timeout(
                    DomainSkill().run(action="suggest_domains", name=business_name),
                    timeout=20,
                )

            if "chatbot" not in executed_results:
                executed_results["chatbot"] = await self._run_with_timeout(
                    AIChatbotSkill().run(action="design_chatbot", business_name=business_name, purpose="support"),
                    timeout=20,
                )

            if "automation" not in executed_results:
                executed_results["automation"] = await self._run_with_timeout(
                    AIAutomationSkill().run(action="design_workflow", workflow_name="Order to Fulfillment", trigger="new order"),
                    timeout=20,
                )

            if "dashboard" not in executed_results:
                executed_results["dashboard"] = await self._run_with_timeout(
                    AIAnalystSkill().run(action="create_dashboard", business_name=business_name),
                    timeout=20,
                )

            if "social_calendar" not in executed_results:
                executed_results["social_calendar"] = await self._run_with_timeout(
                    SocialMediaSkill().run(action="create_content_calendar", business_name=business_name, niche=niche),
                    timeout=20,
                )

            state["executed"] = executed_results
            self._save_state(slug, state)

        live_complete = all(k in live_results for k in ("shopify", "stripe", "domain"))

        launch_plan = {
            "phase": "launch",
            "business_name": business_name,
            "niche": niche,
            "platform": platform,
            "budget_usd": budget,
            "automation_level": automation_level,
            "domain": live_results.get("domain", {}).get("domain") or domain_name,
            "steps": [
                {"skill": "dropship_research", "action": "find_trending", "niche": niche},
                {"skill": "dropship_research", "action": "generate_concept", "niche": niche},
                {"skill": "domain", "action": "suggest_domains", "base_name": business_name},
                {"skill": "logo_design", "action": "generate_logo", "business_name": business_name},
                {"skill": "shopify", "action": "create_store", "store_name": business_name, "dry_run": not execute},
                {"skill": "shopify", "action": "add_product", "dry_run": not live_complete},
                {"skill": "stripe", "action": "create_product", "product": {"name": "Signature Product"}, "dry_run": not live_complete},
                {"skill": "email_setup", "action": "setup_email", "business_name": business_name},
                {"skill": "social_media", "action": "create_content_calendar", "business_name": business_name, "niche": niche},
                {"skill": "ai_chatbot", "action": "design_chatbot", "business_name": business_name, "purpose": "support"},
                {"skill": "ai_automation", "action": "design_workflow", "workflow_name": "Order to Fulfillment", "trigger": "new order"},
                {"skill": "ai_analyst", "action": "create_dashboard", "business_name": business_name},
                {"skill": "deploy", "action": "deploy", "target": platform, "dry_run": not live_complete},
            ],
            "autonomous_operations": [
                "AI chatbot answers customer questions 24/7",
                "Automation forwards orders and sends tracking updates",
                "Weekly AI analyst report with recommendations",
                "Social media content calendar auto-generated",
            ] if automation_level == "full" else [
                "AI chatbot answers common questions",
                "Order notification automation",
            ],
            "dry_run": not live_complete,
            "executed": executed_results if execute else None,
            "live_results": live_results if execute else None,
            "next_command": f"Run `ai_run_business.operate` with business_name='{business_name}' to start operations after launch.",
        }

        return launch_plan

    # ---------- live commerce setup ----------

    async def _setup_shopify(self, business_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Verify Shopify credentials/store and add a flagship product."""
        shopify = ShopifySkill()

        # This will return needs_auth if either the access token or store_url is missing.
        store_info = await shopify.run(action="get_store", dry_run=False)
        if store_info.get("needs_auth"):
            return store_info

        store_url = await shopify._resolve_store_url(kwargs) or ""
        product = {
            "title": f"{business_name} Signature Product",
            "body_html": f"<p>The flagship product from {business_name}.</p>",
            "vendor": business_name,
            "product_type": "Signature",
            "variants": [
                {
                    "price": "29.99",
                    "requires_shipping": True,
                    "taxable": True,
                    "inventory_management": "shopify",
                    "inventory_quantity": 100,
                },
            ],
            "tags": "bestseller, launch",
        }
        add_res = await shopify.run(action="add_product", store_url=store_url, product=product, dry_run=False)
        if add_res.get("needs_auth"):
            return add_res
        return {"store": store_info, "add_product": add_res}

    async def _setup_stripe(self, business_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Create a Stripe product, price, and payment link."""
        stripe = StripeSkill()

        product_payload = {
            "name": f"{business_name} Signature Product",
            "description": f"Flagship product from {business_name}.",
        }
        product = await stripe.run(action="create_product", product=product_payload, dry_run=False)
        if product.get("needs_auth"):
            return product

        product_id = product.get("product", {}).get("id")
        if not product_id:
            return {"error": "Stripe product creation did not return an ID", "product": product}

        price_payload = {
            "unit_amount": 2999,
            "currency": "usd",
            "product": product_id,
        }
        price = await stripe.run(action="create_price", price=price_payload, dry_run=False)
        if price.get("needs_auth"):
            return price

        price_id = price.get("price", {}).get("id")
        if not price_id:
            return {"error": "Stripe price creation did not return an ID", "price": price}

        link_payload = {
            "line_items": [{"price": price_id, "quantity": 1}],
        }
        link = await stripe.run(action="create_payment_link", payment_link=link_payload, dry_run=False)
        return {"product": product, "price": price, "payment_link": link}

    async def _setup_domain(
        self,
        business_name: str,
        kwargs: dict[str, Any],
        domain_name: str | None,
        registrar: str,
    ) -> dict[str, Any]:
        """Pick an available domain and prepare a live purchase."""
        domain_skill = DomainSkill()

        if not domain_name:
            suggestions = await domain_skill.run(action="suggest_domains", name=business_name)
            available = [s for s in suggestions.get("suggestions", []) if s.get("available")]
            if not available:
                return {"error": "No available domain suggestions found"}
            domain_name = available[0]["domain"]

        purchase = await domain_skill.run(
            action="prepare_purchase",
            domain=domain_name,
            registrar=registrar,
            dry_run=False,
        )
        if purchase.get("needs_auth"):
            return purchase
        return {"domain": domain_name, "purchase": purchase}

    # ---------- operate / report ----------

    async def _operate(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business_name = kwargs.get("business_name", "My AI Business")

        operations = {
            "phase": "operate",
            "business_name": business_name,
            "active_automations": [
                {"name": "Customer Support Chatbot", "skill": "ai_chatbot", "status": "running"},
                {"name": "Order Fulfillment Workflow", "skill": "ai_automation", "status": "running"},
                {"name": "Weekly Analytics Report", "skill": "ai_analyst", "status": "scheduled"},
                {"name": "Social Content Calendar", "skill": "social_media", "status": "scheduled"},
            ],
            "daily_loop": [
                "Check analytics dashboard",
                "Review chatbot conversation logs",
                "Approve or adjust ad spend recommendations",
                "Publish scheduled social posts",
                "Fulfill orders via supplier automation",
            ],
            "ai_decisions": [
                "Auto-adjust product pricing within defined bounds",
                "Pause underperforming ads and scale winners",
                "Reorder best sellers when inventory threshold hit",
                "A/B test email subject lines and product descriptions",
            ],
            "note": "Live operation requires real API credentials and a scheduler/VM. Current output is a plan.",
            "next_command": f"Run `ai_run_business.report` with business_name='{business_name}' for the latest AI analyst report.",
        }

        return operations

    async def _report(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business_name = kwargs.get("business_name", "My AI Business")

        return {
            "phase": "report",
            "business_name": business_name,
            "period": "last 7 days",
            "summary": {
                "revenue": "$0.00 (sample)",
                "orders": 0,
                "visitors": 0,
                "conversion_rate": "0.0% (sample)",
            },
            "ai_generated_insights": [
                "No live data connected yet. Connect Shopify/Stripe analytics for real reports.",
                "Once connected, the analyst will auto-generate weekly recommendations.",
            ],
            "recommended_actions": [
                "Connect Shopify and Stripe to ai_analyst skill",
                "Set up scheduled execution of ai_run_business.report",
                "Enable AI automation workflows in n8n or as Python scripts",
            ],
        }
