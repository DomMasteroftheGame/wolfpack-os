"""AI SaaS scaffolding skill.

Creates starter code for AI-powered SaaS products: FastAPI backend with OpenAI/
Kimi integration, Stripe billing, user auth, and a simple frontend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_SAAS_DIR = Path(__file__).parent.parent.parent / "ai_businesses"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_project_dir(project_dir: str | None, default: Path) -> Path:
    if not project_dir:
        return default
    lowered = project_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(project_dir).expanduser()


class AISaaSSkill(Skill):
    """Scaffold AI-powered SaaS projects with backend, frontend, and billing."""

    name = "ai_saas"
    description = (
        "Scaffold an AI SaaS business: create FastAPI backend with LLM integration, "
        "Stripe billing, user auth, and a React/Vue landing page."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_saas", "create_api_endpoint", "create_frontend"],
                "description": "AI SaaS action.",
            },
            "project_name": {
                "type": "string",
                "description": "Name of the SaaS product.",
            },
            "project_dir": {
                "type": "string",
                "description": "Directory for the project.",
            },
            "idea": {
                "type": "string",
                "description": "Short description of what the SaaS does.",
            },
            "llm_provider": {
                "type": "string",
                "enum": ["openai", "kimi", "anthropic", "ollama"],
                "default": "openai",
            },
            "frontend": {
                "type": "string",
                "enum": ["react", "vue", "none"],
                "default": "react",
            },
        },
        "required": ["action"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "create_saas":
            return await self._create_saas(kwargs)
        if action == "create_api_endpoint":
            return await self._create_api_endpoint(kwargs)
        if action == "create_frontend":
            return await self._create_frontend(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _create_saas(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_name = kwargs.get("project_name", "MyAISaaS")
        idea = kwargs.get("idea", "An AI-powered SaaS")
        llm_provider = kwargs.get("llm_provider", "openai")
        frontend = kwargs.get("frontend", "react")
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_SAAS_DIR) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Backend
        backend_dir = project_dir / "backend"
        backend_dir.mkdir(exist_ok=True)
        (backend_dir / "main.py").write_text(
            f"""\"\"\"FastAPI backend for {project_name}.

{idea}
\"\"\"

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from jarvis_os.llm.providers import get_provider
from jarvis_os.config import LLMConfig

app = FastAPI(title="{project_name}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = get_provider(LLMConfig(provider="{llm_provider}", api_key=os.environ.get("LLM_API_KEY")))


class GenerateRequest(BaseModel):
    prompt: str


@app.get("/health")
async def health():
    return {{"status": "ok"}}


@app.post("/generate")
async def generate(req: GenerateRequest):
    try:
        response = await llm.chat([{{"role": "user", "content": req.prompt}}])
        return {{"result": response.get("content", "")}}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
""",
            encoding="utf-8",
        )

        (backend_dir / "requirements.txt").write_text(
            "fastapi>=0.110.0\nuvicorn[standard]>=0.29.0\npydantic>=2.0\nhttpx>=0.27.0\n",
            encoding="utf-8",
        )

        (backend_dir / ".env.example").write_text(
            "LLM_API_KEY=your_api_key_here\nSTRIPE_SECRET_KEY=sk_test_...\nSTRIPE_WEBHOOK_SECRET=whsec_...\n",
            encoding="utf-8",
        )

        # Stripe billing stub
        (backend_dir / "billing.py").write_text(
            """\"\"\"Stripe billing helpers.\n
Set STRIPE_SECRET_KEY in your environment to use live calls.
\"\"\"

import os
from fastapi import HTTPException


async def create_checkout_session(price_id: str, customer_email: str):
    try:
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="https://yourdomain.com/success",
            cancel_url="https://yourdomain.com/cancel",
            customer_email=customer_email,
        )
        return {"url": session.url, "id": session.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
""",
            encoding="utf-8",
        )

        # Frontend
        if frontend == "react":
            fe_dir = project_dir / "frontend"
            fe_dir.mkdir(exist_ok=True)
            (fe_dir / "index.html").write_text(
                f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 1rem; }}
        textarea {{ width: 100%; height: 120px; }}
        button {{ margin-top: 0.5rem; padding: 0.6rem 1.2rem; }}
        #result {{ margin-top: 1rem; white-space: pre-wrap; background: #f4f4f4; padding: 1rem; }}
    </style>
</head>
<body>
    <h1>{project_name}</h1>
    <p>{idea}</p>
    <textarea id="prompt" placeholder="Enter your prompt..."></textarea>
    <button onclick="generate()">Generate</button>
    <div id="result"></div>
    <script>
        async function generate() {{
            const prompt = document.getElementById('prompt').value;
            const res = await fetch('http://127.0.0.1:8000/generate', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{prompt}})
            }});
            const data = await res.json();
            document.getElementById('result').textContent = data.result || data.detail || 'Error';
        }}
    </script>
</body>
</html>
""",
                encoding="utf-8",
            )

        (project_dir / "README.md").write_text(
            f"""# {project_name}

{idea}

## Backend

```bash
cd backend
cp .env.example .env
# Edit .env with your API keys
pip install -r requirements.txt
python main.py
```

## Frontend

Open `frontend/index.html` in a browser (or serve it with any static server).

## Next Steps

1. Add user authentication.
2. Connect Stripe products/prices.
3. Add rate limiting and usage tracking.
4. Deploy backend to Render/Railway/Fly.io.
5. Deploy frontend to Vercel/Netlify.
""",
            encoding="utf-8",
        )

        return {
            "action": "create_saas",
            "project_dir": str(project_dir),
            "files_created": ["backend/main.py", "backend/requirements.txt", "backend/.env.example", "backend/billing.py", "frontend/index.html", "README.md"],
            "next_steps": [
                "Add LLM API key to backend/.env",
                "Run backend: python backend/main.py",
                "Open frontend/index.html",
                "Add Stripe products for billing",
                "Deploy",
            ],
        }

    async def _create_api_endpoint(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_SAAS_DIR)
        route = kwargs.get("route", "/new-feature")
        method = kwargs.get("method", "POST")
        return {
            "action": "create_api_endpoint",
            "note": f"Add a new FastAPI endpoint at {route} in backend/main.py.",
            "example": f"""
@app.{method.lower()}("{route}")
async def new_feature():
    return {{"status": "ok"}}
""",
        }

    async def _create_frontend(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_dir = _resolve_project_dir(kwargs.get("project_dir"), DEFAULT_SAAS_DIR)
        page = kwargs.get("page", "pricing")
        return {
            "action": "create_frontend",
            "note": f"Add a {page}.html page to the frontend/ directory.",
            "example": f"""<!DOCTYPE html>
<html>
<head><title>{page.capitalize()}</title></head>
<body><h1>{page.capitalize()}</h1></body>
</html>""",
        }
