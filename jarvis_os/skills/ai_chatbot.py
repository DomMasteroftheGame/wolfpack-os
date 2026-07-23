"""AI chatbot skill.

Creates customer-service chatbot configurations, knowledge bases, and response
prompts for AI-run businesses.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_CHATBOT_DIR = Path(__file__).parent.parent.parent / "ai_businesses" / "chatbots"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class AIChatbotSkill(Skill):
    """Set up AI customer-service chatbots for AI-run businesses."""

    name = "ai_chatbot"
    description = (
        "Create AI chatbot configurations, knowledge bases, and response prompts "
        "for customer support, sales, and onboarding."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["design_chatbot", "create_knowledge_base", "create_prompt"],
                "description": "Chatbot action.",
            },
            "business_name": {
                "type": "string",
                "description": "Name of the business.",
            },
            "purpose": {
                "type": "string",
                "enum": ["support", "sales", "onboarding", "general"],
                "default": "support",
            },
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topics the chatbot should handle.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save chatbot files.",
            },
        },
        "required": ["action", "business_name"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "design_chatbot":
            return await self._design_chatbot(kwargs)
        if action == "create_knowledge_base":
            return await self._create_knowledge_base(kwargs)
        if action == "create_prompt":
            return await self._create_prompt(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _design_chatbot(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        purpose = kwargs.get("purpose", "support")
        topics = kwargs.get("topics", [])

        platforms = ["Chatbase", "Intercom Fin", "Crisp", "Tidio", "Voiceflow", "n8n + OpenAI"]

        return {
            "action": "design_chatbot",
            "business_name": business,
            "purpose": purpose,
            "topics": topics or ["pricing", "shipping", "returns", "product questions"],
            "recommended_platforms": platforms,
            "handoff_rules": [
                "Escalate to human if customer asks for refund over $50",
                "Escalate if sentiment is strongly negative",
                "Escalate if issue is legal/compliance related",
            ],
            "next_steps": [
                "Create knowledge base documents",
                "Write system prompt",
                "Connect to website/Shopify",
                "Test with 20 common questions",
                "Set up analytics",
            ],
        }

    async def _create_knowledge_base(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        topics = kwargs.get("topics", [])
        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_CHATBOT_DIR / business.lower().replace(" ", "_"))
        output_dir.mkdir(parents=True, exist_ok=True)

        docs = []
        default_topics = topics or ["About Us", "Shipping", "Returns", "Pricing", "FAQ"]
        for topic in default_topics:
            filename = output_dir / f"{topic.lower().replace(' ', '_')}.md"
            content = f"""# {topic}

## Overview

Information about {topic} for {business}.

## Details

- Point 1 about {topic}
- Point 2 about {topic}
- Common question and answer about {topic}

## Related

See also other knowledge base articles.
"""
            filename.write_text(content, encoding="utf-8")
            docs.append(str(filename))

        return {
            "action": "create_knowledge_base",
            "files": docs,
            "next_step": "Upload these files to your chatbot platform as context.",
        }

    async def _create_prompt(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        purpose = kwargs.get("purpose", "support")
        topics = kwargs.get("topics", [])

        prompt = f"""You are the AI support assistant for {business}.

Purpose: {purpose}
Topics you can help with: {', '.join(topics) or 'general questions'}.

Rules:
- Be friendly, concise, and helpful.
- Only answer based on the provided knowledge base.
- If you don't know the answer, say so and offer to escalate to a human.
- Never make up policies, prices, or shipping times.
- Ask clarifying questions if the user's request is unclear.
- For refund/escalation requests, collect order number and reason, then hand off.

When replying, use the customer's name if provided and end with a clear next step.
"""
        return {
            "action": "create_prompt",
            "prompt": prompt,
            "note": "Paste this as the system prompt in your chatbot platform.",
        }
