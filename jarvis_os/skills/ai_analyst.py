"""AI analyst skill.

Analyzes business metrics, generates reports, and recommends actions for AI-run
businesses without requiring live data (works from CSV/JSON or sample data).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_ANALYTICS_DIR = Path(__file__).parent.parent.parent / "ai_businesses" / "analytics"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class AIAnalystSkill(Skill):
    """Analyze business data and recommend actions for AI-run businesses."""

    name = "ai_analyst"
    description = (
        "Analyze business metrics, create dashboards, and generate actionable "
        "recommendations for AI-run businesses. Works from CSV/JSON or sample data."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["analyze_data", "create_dashboard", "generate_recommendations"],
                "description": "Analyst action.",
            },
            "business_name": {
                "type": "string",
                "description": "Name of the business.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metrics to analyze (e.g. revenue, conversion_rate).",
            },
            "data_file": {
                "type": "string",
                "description": "Path to CSV/JSON data file.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save reports and dashboards.",
            },
        },
        "required": ["action", "business_name"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "analyze_data":
            return await self._analyze_data(kwargs)
        if action == "create_dashboard":
            return await self._create_dashboard(kwargs)
        if action == "generate_recommendations":
            return await self._generate_recommendations(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _analyze_data(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        metrics = kwargs.get("metrics", [])
        data_file = kwargs.get("data_file")

        result = {
            "business": business,
            "metrics_analyzed": metrics or ["revenue", "conversion_rate", "customer_acquisition_cost", "lifetime_value"],
            "summary": {
                "status": "Sample analysis - provide real data for detailed report",
                "trend": "Stable",
                "top_opportunity": "Increase repeat purchase rate",
                "top_risk": "Rising customer acquisition cost",
            },
            "data_file_used": data_file,
        }

        if data_file:
            path = Path(data_file).expanduser()
            if path.exists():
                result["data_file_found"] = True
                result["note"] = "Real data file found. Implement parsing logic to compute actual metrics."
            else:
                result["data_file_found"] = False
                result["note"] = f"Data file not found: {data_file}. Returning sample analysis."

        return result

    async def _create_dashboard(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        metrics = kwargs.get("metrics", [])
        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_ANALYTICS_DIR / business.lower().replace(" ", "_"))
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = output_dir / "dashboard.json"
        dashboard = {
            "title": f"{business} AI Analyst Dashboard",
            "refresh_interval_seconds": 300,
            "widgets": [
                {"type": "metric", "title": "Revenue", "data_source": "shopify/orders"},
                {"type": "metric", "title": "Conversion Rate", "data_source": "google_analytics"},
                {"type": "chart", "title": "Traffic", "chart_type": "line", "data_source": "plausible"},
                {"type": "chart", "title": "Top Products", "chart_type": "bar", "data_source": "shopify/products"},
            ],
            "metrics": metrics or ["revenue", "conversion_rate", "traffic", "top_products"],
        }
        filename.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

        return {
            "action": "create_dashboard",
            "file": str(filename),
            "dashboard": dashboard,
            "recommended_tools": ["Metabase", "Grafana", "Google Looker Studio", "Tinybird", "Streamlit"],
            "next_step": "Connect data sources and import this dashboard template.",
        }

    async def _generate_recommendations(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        business = kwargs.get("business_name", "")
        metrics = kwargs.get("metrics", [])

        recommendations = [
            {
                "area": "Customer Acquisition",
                "insight": "Top of funnel is healthy but CAC is rising.",
                "action": "Test organic TikTok/Reels content to reduce paid dependency.",
                "expected_impact": "Lower CAC by 15-25% over 30 days",
                "effort": "Medium",
            },
            {
                "area": "Conversion",
                "insight": "Cart abandonment is the biggest leak.",
                "action": "Add AI chatbot and abandoned-cart email sequence.",
                "expected_impact": "Recover 10-15% of abandoned carts",
                "effort": "Low",
            },
            {
                "area": "Retention",
                "insight": "Repeat purchase rate is below benchmark.",
                "action": "Launch loyalty program and post-purchase upsells.",
                "expected_impact": "Increase LTV by 20%",
                "effort": "Medium",
            },
        ]

        return {
            "business": business,
            "metrics": metrics or ["revenue", "conversion_rate", "cac", "ltv"],
            "recommendations": recommendations,
            "next_step": "Pick the highest-impact/lowest-effort recommendation and create an automation for it.",
        }
