"""Google connector skill for Gmail and Calendar."""

from pathlib import Path
from typing import Any

from jarvis_os.connectors.google import GoogleConnector
from jarvis_os.skills.base import Skill


class GoogleConnectorSkill(Skill):
    """Read Gmail and Google Calendar via OAuth."""

    name = "google"
    description = "Authenticate with Google and read Gmail messages or Calendar events."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["auth", "gmail_list", "gmail_read", "calendar_list"],
            },
            "query": {"type": "string", "default": ""},
            "message_id": {"type": "string"},
            "max_results": {"type": "integer", "default": 10},
            "days": {"type": "integer", "default": 7},
        },
        "required": ["action"],
    }
    permissions = ["google:read"]

    def __init__(self, credentials_file: str = "data/google_credentials.json", client_secrets_file: str | None = None):
        self.credentials_file = credentials_file
        self.client_secrets_file = client_secrets_file
        self._connector: GoogleConnector | None = None

    def _get_connector(self) -> GoogleConnector:
        if self._connector is None:
            self._connector = GoogleConnector(self.credentials_file, self.client_secrets_file)
        return self._connector

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs["action"]
        connector = self._get_connector()

        if action == "auth":
            # OAuth flow is synchronous and interactive; run in thread
            import asyncio
            return await asyncio.to_thread(connector.authenticate)

        if action == "gmail_list":
            return await connector.gmail_list(
                query=kwargs.get("query", ""),
                max_results=kwargs.get("max_results", 10),
            )

        if action == "gmail_read":
            message_id = kwargs.get("message_id")
            if not message_id:
                return {"error": "message_id is required"}
            return await connector.gmail_read(message_id)

        if action == "calendar_list":
            return await connector.calendar_list(
                days=kwargs.get("days", 7),
                max_results=kwargs.get("max_results", 10),
            )

        return {"error": f"Unknown action: {action}"}
