"""Social media setup skill.

Generates platform-specific bios, username suggestions, and content ideas.
Does not automate account creation (most platforms block/ban bots).
"""

from __future__ import annotations

from typing import Any

from jarvis_os.skills.base import Skill


class SocialMediaSkill(Skill):
    """Plan social media presence for a brand or game."""

    name = "social_media"
    description = (
        "Generate bios, username ideas, and content plans for TikTok, Instagram, "
        "X/Twitter, YouTube, and Facebook. Does not create accounts automatically."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_presence", "content_plan"],
                "description": "Social media action.",
            },
            "brand_name": {
                "type": "string",
                "description": "Brand or project name.",
            },
            "niche": {
                "type": "string",
                "description": "Brand niche or product category.",
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Platforms to target. Defaults to all major ones.",
            },
        },
        "required": ["action", "brand_name"],
    }
    permissions = ["social:plan"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "generate_presence":
            return await self._generate_presence(kwargs)
        if action == "content_plan":
            return await self._content_plan(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _generate_presence(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        brand = kwargs.get("brand_name", "")
        niche = kwargs.get("niche", "")
        platforms = kwargs.get("platforms", ["tiktok", "instagram", "x", "youtube", "facebook"])

        slug = "".join(c for c in brand if c.isalnum()).lower()

        templates = {
            "tiktok": f"{brand} | {niche} 🔥 Watch us build in public. New drops weekly. ⬇️ Shop link in bio",
            "instagram": f"{brand} ✨ {niche}. DM for collabs. Shop the collection ⬇️",
            "x": f"{brand} — {niche}. Building in public. New drops & behind-the-scenes.",
            "youtube": f"{brand}: {niche} reviews, tutorials, and behind-the-scenes builds.",
            "facebook": f"{brand} | {niche}. Join our community for exclusive drops and support.",
        }

        result = {}
        for platform in platforms:
            result[platform] = {
                "username_suggestions": [
                    f"@{slug}",
                    f"@get{slug}",
                    f"@{slug}official",
                    f"@shop{slug}",
                ],
                "bio": templates.get(platform, f"{brand} — {niche}"),
                "signup_url": self._signup_url(platform),
            }

        return {
            "action": "generate_presence",
            "brand_name": brand,
            "niche": niche,
            "profiles": result,
        }

    async def _content_plan(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        brand = kwargs.get("brand_name", "")
        niche = kwargs.get("niche", "")
        platforms = kwargs.get("platforms", ["tiktok", "instagram"])

        ideas = {
            "tiktok": [
                "Day-in-the-life packing orders",
                "Product demo with trending sound",
                "Before/after using the product",
                "Myth-busting video about the niche",
                "Customer unboxing reaction",
            ],
            "instagram": [
                "Product flat lay carousel",
                "Behind-the-scenes Reel",
                "User-generated content repost",
                "Founder story post",
                "Limited-time offer graphic",
            ],
            "x": [
                "Build-in-public thread",
                "Customer testimonial quote",
                "Quick tip related to the niche",
                "Poll about next product",
                "Launch announcement",
            ],
            "youtube": [
                "Unboxing and first impressions",
                "Niche beginner's guide",
                "Comparison video vs competitors",
                "Setup/tutorial video",
                "Monthly recap / what sold",
            ],
            "facebook": [
                "Community question post",
                "Customer review spotlight",
                "Flash sale announcement",
                "Live Q&A with founder",
                "Educational article share",
            ],
        }

        plan = {}
        for platform in platforms:
            plan[platform] = ideas.get(platform, ["Post about " + brand])

        return {
            "action": "content_plan",
            "brand_name": brand,
            "niche": niche,
            "content_plan": plan,
        }

    def _signup_url(self, platform: str) -> str:
        urls = {
            "tiktok": "https://www.tiktok.com/signup",
            "instagram": "https://www.instagram.com/accounts/emailsignup/",
            "x": "https://twitter.com/i/flow/signup",
            "youtube": "https://www.youtube.com/signin",
            "facebook": "https://www.facebook.com/r.php",
        }
        return urls.get(platform, "")
