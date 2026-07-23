"""Business email setup skill.

Prepares setup plans for Google Workspace, Zoho Mail, and Microsoft 365
business email. Live provisioning requires admin credentials.
"""

from __future__ import annotations

from typing import Any

from jarvis_os.skills.base import Skill


class EmailSetupSkill(Skill):
    """Plan and prepare business email configuration."""

    name = "email_setup"
    description = (
        "Prepare business email setup for Google Workspace, Zoho Mail, or "
        "Microsoft 365, including DNS records and admin user provisioning."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["plan_setup", "generate_dns_records"],
                "description": "Email setup action.",
            },
            "provider": {
                "type": "string",
                "enum": ["google_workspace", "zoho_mail", "microsoft_365"],
                "default": "google_workspace",
                "description": "Email provider.",
            },
            "domain": {
                "type": "string",
                "description": "Domain to use for email addresses.",
            },
            "users": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of users to create (name, email alias).",
            },
        },
        "required": ["action", "domain"],
    }
    permissions = ["email:plan"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "plan_setup":
            return await self._plan_setup(kwargs)
        if action == "generate_dns_records":
            return await self._dns_records(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _plan_setup(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        provider = kwargs.get("provider", "google_workspace")
        domain = kwargs.get("domain", "")
        users = kwargs.get("users", [])

        if not domain:
            return {"error": "domain is required for plan_setup"}

        plans = {
            "google_workspace": {
                "signup_url": f"https://workspace.google.com/business/signup/welcome?ddm1={domain}",
                "admin_console": "https://admin.google.com",
                "pricing": "$6/user/month (Business Starter)",
                "mx_records": [
                    {"priority": 1, "value": "ASPMX.L.GOOGLE.COM."},
                    {"priority": 5, "value": "ALT1.ASPMX.L.GOOGLE.COM."},
                    {"priority": 5, "value": "ALT2.ASPMX.L.GOOGLE.COM."},
                    {"priority": 10, "value": "ALT3.ASPMX.L.GOOGLE.COM."},
                    {"priority": 10, "value": "ALT4.ASPMX.L.GOOGLE.COM."},
                ],
            },
            "zoho_mail": {
                "signup_url": "https://www.zoho.com/mail/zohomail-pricing.html",
                "admin_console": "https://mail.zoho.com",
                "pricing": "$1/user/month (Mail Lite)",
                "mx_records": [
                    {"priority": 10, "value": "mx.zoho.com."},
                    {"priority": 20, "value": "mx2.zoho.com."},
                    {"priority": 50, "value": "mx3.zoho.com."},
                ],
            },
            "microsoft_365": {
                "signup_url": "https://www.microsoft.com/en-us/microsoft-365/business",
                "admin_console": "https://admin.microsoft.com",
                "pricing": "$6/user/month (Business Basic)",
                "mx_records": [
                    {"priority": 0, "value": f"{domain}.mail.protection.outlook.com."},
                ],
            },
        }

        plan = plans.get(provider, plans["google_workspace"])
        return {
            "action": "plan_setup",
            "provider": provider,
            "domain": domain,
            "users_to_create": users or [{"alias": "hello", "email": f"hello@{domain}"}],
            "signup_url": plan["signup_url"],
            "admin_console": plan["admin_console"],
            "pricing": plan["pricing"],
            "dns_records": plan["mx_records"],
            "next_steps": [
                "Sign up at the provider URL.",
                "Verify domain ownership (usually via TXT or CNAME record).",
                "Add the MX records to your DNS.",
                "Create user mailboxes.",
            ],
        }

    async def _dns_records(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        provider = kwargs.get("provider", "google_workspace")
        domain = kwargs.get("domain", "")
        if not domain:
            return {"error": "domain is required for generate_dns_records"}

        plan = await self._plan_setup(kwargs)
        return {
            "action": "generate_dns_records",
            "provider": provider,
            "domain": domain,
            "mx_records": plan["dns_records"],
            "txt_records": [
                {"name": "@", "value": f"v=spf1 include:{provider.replace('_', '')}.net ~all"},
            ],
        }
