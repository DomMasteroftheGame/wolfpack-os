"""AI content business skill.

Plans and generates content for AI-run content businesses: blog posts, social
media calendars, email sequences, video scripts, and ad copy. Can output prompts
or call an LLM directly if configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_CONTENT_DIR = Path(__file__).parent.parent.parent / "ai_businesses" / "content"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class AIContentSkill(Skill):
    """Generate content packages for AI content businesses."""

    name = "ai_content"
    description = (
        "Generate content packages for an AI content business: blog posts, "
        "social media calendars, email sequences, video scripts, and ad copy."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["content_strategy", "generate_blog_post", "social_calendar", "email_sequence", "ad_copy"],
                "description": "Content action.",
            },
            "topic": {
                "type": "string",
                "description": "Topic or niche for the content.",
            },
            "brand_name": {
                "type": "string",
                "description": "Brand or business name.",
            },
            "audience": {
                "type": "string",
                "description": "Target audience description.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save generated content files.",
            },
        },
        "required": ["action", "topic"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "content_strategy":
            return await self._content_strategy(kwargs)
        if action == "generate_blog_post":
            return await self._generate_blog_post(kwargs)
        if action == "social_calendar":
            return await self._social_calendar(kwargs)
        if action == "email_sequence":
            return await self._email_sequence(kwargs)
        if action == "ad_copy":
            return await self._ad_copy(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _content_strategy(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        topic = kwargs.get("topic", "")
        brand = kwargs.get("brand_name", "")
        audience = kwargs.get("audience", "")

        return {
            "action": "content_strategy",
            "topic": topic,
            "brand_name": brand,
            "audience": audience,
            "content_pillars": [
                f"Educational guides about {topic}",
                f"Case studies and success stories in {topic}",
                f"Tools and resource roundups for {topic}",
                f"Behind-the-scenes / founder journey content",
                f"Trending news and commentary in {topic}",
            ],
            "content_types": ["blog posts", "social media carousels", "short-form video scripts", "email newsletters", "lead magnets"],
            "posting_frequency": {
                "blog": "2-4 posts per week",
                "social": "1-2 posts per day",
                "email": "1 newsletter per week",
                "video": "3-5 short videos per week",
            },
            "monetization": ["affiliate marketing", "sponsored posts", "digital products", "paid newsletter", "consulting leads"],
        }

    async def _generate_blog_post(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        topic = kwargs.get("topic", "")
        brand = kwargs.get("brand_name", "")
        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_CONTENT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        slug = "".join(c if c.isalnum() else "-" for c in topic.lower()).strip("-")
        filename = output_dir / f"{slug}.md"

        content = f"""# {topic}

**By {brand or 'AI Content Team'}**

## Introduction

In this guide, we'll cover everything you need to know about {topic}. Whether you're just getting started or looking to level up, this post will give you actionable insights.

## Why {topic} Matters

- It drives measurable results.
- It saves time and reduces costs.
- It scales without proportional effort.

## 5 Key Strategies

1. **Strategy One** — Start with a clear goal.
2. **Strategy Two** — Use the right tools.
3. **Strategy Three** — Automate repetitive tasks.
4. **Strategy Four** — Measure and iterate.
5. **Strategy Five** — Build systems, not one-offs.

## Conclusion

{topic} is one of the highest-leverage areas to invest in right now. Start small, track results, and scale what works.

---
*Prompt used: Write a comprehensive blog post about {topic}.*
"""
        filename.write_text(content, encoding="utf-8")
        return {
            "action": "generate_blog_post",
            "file": str(filename),
            "title": topic,
            "note": "Expand each section with research and examples before publishing.",
        }

    async def _social_calendar(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        topic = kwargs.get("topic", "")
        brand = kwargs.get("brand_name", "")

        posts = [
            {"day": "Monday", "format": "Educational carousel", "idea": f"5 myths about {topic} debunked"},
            {"day": "Tuesday", "format": "Short video", "idea": f"Quick tip: how to get started with {topic}"},
            {"day": "Wednesday", "format": "Poll/engagement", "idea": f"What's your biggest challenge with {topic}?"},
            {"day": "Thursday", "format": "Case study", "idea": f"How one business used {topic} to 10x results"},
            {"day": "Friday", "format": "Behind-the-scenes", "idea": f"Tools we use for {topic} at {brand or 'our agency'}"},
            {"day": "Saturday", "format": "Meme/relatable", "idea": f"When you finally automate {topic}"},
            {"day": "Sunday", "format": "Long-form thread", "idea": f"Complete beginner's guide to {topic}"},
        ]
        return {
            "action": "social_calendar",
            "topic": topic,
            "brand_name": brand,
            "week_plan": posts,
        }

    async def _email_sequence(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        topic = kwargs.get("topic", "")
        brand = kwargs.get("brand_name", "")

        sequence = [
            {
                "day": 1,
                "subject": f"Welcome to {brand or 'our community'}",
                "body": f"Thanks for joining. Over the next few days, you'll learn how to master {topic}.",
            },
            {
                "day": 2,
                "subject": f"The #1 mistake people make with {topic}",
                "body": f"Most people overcomplicate {topic}. Here's the simple framework that works.",
            },
            {
                "day": 3,
                "subject": f"Case study: {topic} in action",
                "body": f"See how a real business used {topic} to get results in 30 days.",
            },
            {
                "day": 5,
                "subject": f"Ready to implement {topic}?",
                "body": f"Here's a step-by-step checklist to get {topic} working for you this week.",
            },
        ]
        return {
            "action": "email_sequence",
            "topic": topic,
            "brand_name": brand,
            "sequence": sequence,
        }

    async def _ad_copy(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        topic = kwargs.get("topic", "")
        brand = kwargs.get("brand_name", "")

        return {
            "action": "ad_copy",
            "topic": topic,
            "brand_name": brand,
            "facebook_ad": {
                "headline": f"Stop Struggling With {topic}",
                "primary_text": f"Discover the easiest way to master {topic} without wasting hours. Join {brand or 'thousands'} who already made the switch.",
                "cta": "Learn More",
            },
            "google_ad": {
                "headline_1": f"Master {topic} Fast",
                "headline_2": f"{topic} Made Simple",
                "description": f"Save time and get better results with {topic}. Start your free guide today.",
            },
            "tiktok_hook": f"POV: you finally figured out {topic} and your results doubled overnight.",
        }
