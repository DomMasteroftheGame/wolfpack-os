"""Business formation skill.

Prepares payloads for LLC formation and EIN acquisition through popular
providers. Live filing always requires human approval and provider credentials.
"""

from __future__ import annotations

from typing import Any

from jarvis_os.skills.base import Skill


class BusinessFormationSkill(Skill):
    """Prepare business formation filings (LLC, EIN)."""

    name = "business_formation"
    description = (
        "Prepare LLC formation and EIN application payloads for LegalZoom, "
        "Stripe Atlas, Clerky, and IRS. Dry-run / planning only."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["form_llc", "apply_ein", "prepare_operating_agreement"],
                "description": "Business formation action.",
            },
            "provider": {
                "type": "string",
                "enum": ["stripe_atlas", "legalzoom", "clerky", "irs"],
                "default": "stripe_atlas",
                "description": "Formation provider or filing authority.",
            },
            "business_name": {
                "type": "string",
                "description": "Desired business legal name.",
            },
            "state": {
                "type": "string",
                "description": "US state for LLC formation (e.g. Delaware, Wyoming).",
            },
            "owner_info": {
                "type": "object",
                "description": "Owner name, SSN/EIN, address, etc.",
            },
            "business_type": {
                "type": "string",
                "enum": ["LLC", "C-Corp", "S-Corp"],
                "default": "LLC",
            },
        },
        "required": ["action"],
    }
    permissions = ["business:plan"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "form_llc":
            return await self._form_llc(kwargs)
        if action == "apply_ein":
            return await self._apply_ein(kwargs)
        if action == "prepare_operating_agreement":
            return await self._operating_agreement(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _form_llc(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("business_name", "")
        state = kwargs.get("state", "Delaware")
        provider = kwargs.get("provider", "stripe_atlas")
        business_type = kwargs.get("business_type", "LLC")
        owner = kwargs.get("owner_info", {})

        if not name:
            return {"error": "business_name is required for form_llc"}

        payload = {
            "company_name": name,
            "company_type": business_type,
            "state": state,
            "owner": owner,
        }

        notes = {
            "stripe_atlas": "Stripe Atlas forms a Delaware C-Corp or LLC and provides EIN assistance.",
            "legalzoom": "LegalZoom supports LLC formation in all 50 states with optional EIN.",
            "clerky": "Clerk supports Delaware C-Corp/LLC formation for startups.",
        }

        return {
            "action": "form_llc",
            "provider": provider,
            "dry_run": True,
            "note": notes.get(provider, "Choose a formation provider and supply credentials to file live."),
            "payload": payload,
            "estimated_cost_usd": {"stripe_atlas": 500, "legalzoom": 79, "clerky": 799}.get(provider, "varies"),
            "next_steps": [
                "Confirm business name availability in the chosen state.",
                "File formation paperwork with the selected provider.",
                "Obtain EIN from the IRS.",
                "Open business bank account.",
            ],
        }

    async def _apply_ein(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("business_name", "")
        owner = kwargs.get("owner_info", {})
        if not name:
            return {"error": "business_name is required for apply_ein"}

        return {
            "action": "apply_ein",
            "authority": "IRS",
            "dry_run": True,
            "note": (
                "EIN applications are filed via IRS Form SS-4. Automated filing is not "
                "supported by most providers; use the IRS online assistant or submit SS-4."
            ),
            "payload": {
                "business_name": name,
                "responsible_party": owner.get("name"),
                "ssn_or_ein": owner.get("ssn_or_ein"),
                "business_address": owner.get("address"),
                "business_type": "LLC",
            },
            "irs_online": "https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online",
        }

    async def _operating_agreement(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("business_name", "")
        state = kwargs.get("state", "Delaware")
        if not name:
            return {"error": "business_name is required for prepare_operating_agreement"}

        template = f"""OPERATING AGREEMENT

{name}, {state} LLC

Article I: Formation
The Members form a limited liability company under the laws of {state}.

Article II: Name and Principal Place of Business
The name of the Company is {name}.
The principal place of business shall be determined by the Members.

Article III: Members
The Company may have one or more Members. Ownership interests are recorded in Schedule A.

Article IV: Management
The Company is managed by its Members unless otherwise designated.

Article V: Distributions
Profits and losses are allocated in proportion to ownership interests.

Article VI: Dissolution
The Company dissolves upon unanimous Member consent or as required by law.

This agreement is a template and should be reviewed by an attorney before execution.
"""
        return {
            "action": "prepare_operating_agreement",
            "business_name": name,
            "state": state,
            "template": template,
            "note": "Review with a business attorney before signing.",
        }
