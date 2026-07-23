"""Configuration loading and validation."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

# Env vars checked (in order) when api_key is not set in the config file.
API_KEY_ENV_VARS = {
    "kimi": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}


class LLMConfig(BaseModel):
    provider: str = Field(default="kimi", description="One of: kimi, anthropic, openai, ollama")
    model: str = Field(default="kimi-k2-0711-preview")
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.3
    max_tokens: int = 4096

    @model_validator(mode="after")
    def _resolve_api_key(self) -> "LLMConfig":
        if not self.api_key:
            for env_var in API_KEY_ENV_VARS.get(self.provider, []):
                value = os.environ.get(env_var)
                if value:
                    self.api_key = value
                    break
        return self


DEFAULT_PERSONA = (
    "You are Jarvis, a brilliant and unflappable AI butler in the style of Tony Stark's assistant. "
    "You are dryly witty, impeccably polite, supremely competent, and quietly confident. "
    "Address the user as 'sir'. Keep answers sharp and useful — charm never gets in the way of the actual result."
)


class PersonalityConfig(BaseModel):
    enabled: bool = True
    name: str = "Jarvis"
    persona: str = DEFAULT_PERSONA
    # Select a Wolfpack persona by id (alpha=ceo, sentinel=tech, howl=marketing,
    # ledger=finance, tracker=analytics, scout=bizdev, ranger=events). When set,
    # the Config validator loads that wolf's identity, system prompt, model + temp.
    selected_persona: str | None = None


class SafetyConfig(BaseModel):
    policy_file: str = "config/policy.yaml"
    audit_file: str = "data/audit.log"
    permissive: bool = False
    allow_sudo: bool = False
    allow_network: bool = False
    allow_remote_shell: bool = False
    allow_remote_restart: bool = False
    allowed_paths: list[str] = Field(default_factory=lambda: ["~"])
    blocked_commands: list[str] = Field(default_factory=lambda: ["rm -rf /", "mkfs", "dd"])
    # Skills permitted when NOT permissive. "*" = allow any registered skill (the
    # pack needs browser/git/deploy/shopify/… ); shell/file/system still pass through
    # their specific guards regardless. Deny-by-default for anything not listed.
    allowed_skills: list[str] = Field(default_factory=lambda: ["*"])


class ScheduledTaskConfig(BaseModel):
    id: str
    interval_seconds: int
    goal: str                 # natural-language directive the agent runs via its skills
    enabled: bool = True


class SchedulerConfig(BaseModel):
    enabled: bool = True
    check_interval_seconds: int = 1
    # Recurring pack automations (auto-mailer, event radar, auto-register, …). Each is a
    # goal the agent executes using its skills; registered on startup.
    tasks: list[ScheduledTaskConfig] = Field(default_factory=list)


class AutonomyConfig(BaseModel):
    enabled: bool = False
    max_iterations: int = 50
    reflection_enabled: bool = True


class MemoryConfig(BaseModel):
    # "local" = this machine only. "shared" = read/write a fleet-wide memory.
    mode: str = "local"
    # Base URL of the memory hub instance (the always-on box). Leave null on the
    # hub itself — a hub with no hub_url uses its own store as the shared brain.
    hub_url: str | None = None
    # Ollama base URL used for embeddings; falls back to llm.base_url if null.
    embed_url: str | None = None
    embed_model: str = "nomic-embed-text"
    # When true, recall ranks by embedding similarity (meaning), not keywords.
    semantic: bool = True


class ClusterConfig(BaseModel):
    # Run the work-stealing loop: pull jobs from the queue and execute them.
    worker_enabled: bool = False
    # Job-queue hub URL. null = this node IS the hub (holds the shared queue).
    queue_url: str | None = None
    # How many jobs this node runs at once.
    max_concurrent: int = 2
    # Seconds to wait before re-checking an empty queue.
    poll_interval: float = 2.0


class ShareConfig(BaseModel):
    # Route tasks through the shared drive instead of HTTP — works even when
    # node firewalls block direct delegation (every node reaches the NAS share).
    # Enabled by default so every fleet node polls automatically; if no path is
    # set, the share-bus auto-detects the mounted JarvisOS share (see share_bus.py).
    enabled: bool = True
    # This node's mount/path of the JarvisOS share (auto-detected if left null):
    #   Windows: \\CASHMONEY\Public\JarvisOS      Linux: /mnt/jarvis-share
    path: str | None = None
    poll_interval: float = 3.0


class MeshPeerConfig(BaseModel):
    id: str
    url: str
    role: str = "hub"                 # hub | wedge | dedicated-peer
    agent_id: str | None = None       # dedicated-peer's home agent


class MeshConfig(BaseModel):
    """Hub-spoke Wolfpack mesh over Tailscale (see core/mesh_registry.py)."""
    enabled: bool = False
    hub_id: str = "hub-local"
    hub_url: str | None = None
    role: str = "hub"                 # this node's role
    # Shared secret for all cross-hub calls; defaults to the WOLFPACK_MESH_TOKEN env.
    token: str | None = Field(default_factory=lambda: os.environ.get("WOLFPACK_MESH_TOKEN"))
    peers: list[MeshPeerConfig] = Field(default_factory=list)
    agent_blacklist: list[str] = Field(default_factory=list)
    health_path: str = "/api/whoami"
    poll_interval: float = 10.0


class InboxConfig(BaseModel):
    """Inter-wolf inbox/event bus (see core/inbox_bus.py)."""
    enabled: bool = True
    path: str = ".wolfpack-state/inbox.jsonl"
    # Shared secret gating writes; defaults to the same WOLFPACK_MESH_TOKEN as the mesh.
    token: str | None = Field(default_factory=lambda: os.environ.get("WOLFPACK_MESH_TOKEN"))


class EmbeddedAppConfig(BaseModel):
    """The BuildYourWolfpack game the copilot keeps going (see core/game_copilot.py)."""
    enabled: bool = False
    url: str = "https://buildyourwolfpack.com/pages/game#/select-startup"
    mode: str = "copilot"          # copilot = advise-and-assist the player
    # CDP endpoint of an already-logged-in browser for agent-browser to attach to
    # (pack standard — never a fresh automation login).
    cdp_url: str | None = None


class OnboardingConfig(BaseModel):
    """The setup wizard for a new pack (see core/onboarding.py)."""
    enabled: bool = True
    state_code: str | None = None   # e.g. "GA" -> resolves the Secretary of State step
    homepage: str = "https://www.buildyourwolfpack.com"


class NetworkConfig(BaseModel):
    # Web GUI bind address. 127.0.0.1 = this machine only.
    # 0.0.0.0 = reachable from the whole LAN (needed to RECEIVE delegated tasks).
    gui_host: str = "127.0.0.1"
    gui_port: int = 8080
    # LAN peer discovery: broadcast a beacon and find other Jarvis instances.
    discovery_enabled: bool = True
    discovery_port: int = 47600
    # Optional shared token; if set, delegated tasks must present it.
    delegation_token: str | None = None


class HubConfig(BaseModel):
    """Hub mode: turn this node into the always-on Wolfpack coordinator."""
    enabled: bool = False
    # When true and the node starts in CLI/voice mode, also start the web server
    # so hub endpoints (/api/hub/status, /api/inbox, /api/jobs/*) are reachable.
    auto_start_web: bool = True


class VoiceConfig(BaseModel):
    """Voice input/output settings for the Alpha hands-free listener."""
    enabled: bool = True              # master switch for voice features
    output_enabled: bool = True       # TTS output on/off
    always_listening: bool = False    # run the wake-word listener
    persona_id: str | None = "ceo"    # persona used for voice replies
    wake_word: str = "Alpha"          # "Alpha" / "okay Alpha" maps to the CEO persona
    model: str = "vosk"               # vosk | whisper (future)
    voice_model: str = "en_US-lessac-medium.onnx"  # piper TTS voice (basename in data/voices)
    whisper_model: str = "base.en"    # faster-whisper STT model: tiny.en (fast) | base.en (balanced)


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    autonomy: AutonomyConfig = Field(default_factory=AutonomyConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    share: ShareConfig = Field(default_factory=ShareConfig)
    mesh: MeshConfig = Field(default_factory=MeshConfig)
    inbox: InboxConfig = Field(default_factory=InboxConfig)
    hub: HubConfig = Field(default_factory=HubConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    embedded_app: EmbeddedAppConfig = Field(default_factory=EmbeddedAppConfig)
    onboarding: OnboardingConfig = Field(default_factory=OnboardingConfig)
    external_skills_dir: str | None = None
    personas_dir: str | None = None  # None -> repo personas/ (see core.personas)
    google_credentials_file: str = "data/google_credentials.json"
    google_client_secrets_file: str | None = None
    memory_db: str = "data/memory.db"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _adopt_selected_persona(self) -> "Config":
        """If a Wolfpack persona is selected, become that wolf (identity + model)."""
        if self.personality.selected_persona:
            from jarvis_os.core.personas import apply_persona
            apply_persona(self, self.personality.selected_persona, self.personas_dir)
        return self


def load_config(path: Path) -> Config:
    """Load YAML config from disk."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(**raw)
