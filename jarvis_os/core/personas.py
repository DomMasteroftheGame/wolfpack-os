"""The Wolfpack personas — the 7 wolves, loaded from personas/<id>.md.

Each file carries YAML frontmatter (id, codename, role, domain, model,
temperature, provider, can_delegate_to, description) and a body that is the wolf's
verbatim system prompt (ported from the hub's agent definitions). Selecting a
persona turns a generic Jarvis runtime into a specific wolf — Alpha (CEO),
Sentinel (tech), Howl (marketing), Ledger (finance), Tracker (analytics),
Scout (bizdev), Ranger (events).

Pure module: parses files into `Persona` records. `apply_persona()` (used by the
config layer) maps a persona onto a running Config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# repo-root/personas
DEFAULT_PERSONAS_DIR = Path(__file__).resolve().parent.parent.parent / "personas"


@dataclass
class Persona:
    id: str
    codename: str
    role: str
    domain: str
    system_prompt: str
    model: str = ""
    temperature: float | None = None
    provider: str = ""
    can_delegate_to: list[str] = field(default_factory=list)
    description: str = ""


def _parse(path: Path) -> Persona:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    return Persona(
        id=str(meta.get("id") or path.stem),
        codename=str(meta.get("codename") or meta.get("id") or path.stem),
        role=str(meta.get("role") or ""),
        domain=str(meta.get("domain") or meta.get("role") or ""),
        system_prompt=body.strip(),
        model=str(meta.get("model") or ""),
        temperature=meta.get("temperature"),
        provider=str(meta.get("provider") or ""),
        can_delegate_to=list(meta.get("can_delegate_to") or []),
        description=str(meta.get("description") or ""),
    )


def load_personas(directory: str | Path | None = None) -> dict[str, Persona]:
    d = Path(directory) if directory else DEFAULT_PERSONAS_DIR
    out: dict[str, Persona] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        try:
            persona = _parse(p)
            out[persona.id] = persona
        except Exception as exc:  # noqa: BLE001 — one bad file shouldn't kill the pack
            print(f"Failed to parse persona {p}: {exc}")
    return out


def get_persona(persona_id: str, directory: str | Path | None = None) -> Persona | None:
    personas = load_personas(directory)
    persona = personas.get(persona_id)
    if persona is None:
        # Also accept codenames ("ledger" -> finance, "alpha" -> ceo, ...); the
        # appliance/build pipeline brands peers by codename.
        lowered = persona_id.lower()
        persona = next((p for p in personas.values() if p.codename.lower() == lowered), None)
    return persona


def apply_persona(config, persona_id: str, directory: str | Path | None = None):
    """Mutate a Config to become the given wolf: identity (name + system prompt) and,
    when the persona declares them, the model + temperature. Returns the config."""
    persona = get_persona(persona_id, directory)
    if persona is None:
        raise ValueError(f"Unknown persona: {persona_id}")
    config.personality.name = persona.codename
    config.personality.persona = persona.system_prompt
    if persona.temperature is not None:
        config.llm.temperature = float(persona.temperature)
    # Persona models are Claude model ids — only adopt them on the claude_cli brain.
    # Under a testing provider (e.g. kimi) keep the provider's own model, so a wolf's
    # identity (name + system prompt) still applies without an invalid model.
    if persona.model and config.llm.provider == "claude_cli":
        config.llm.model = persona.model
    return config
