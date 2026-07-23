"""Google API connector for Gmail and Calendar."""

import asyncio
import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class GoogleConnector:
    """Handles OAuth and API calls for Gmail and Google Calendar."""

    def __init__(self, credentials_file: str, client_secrets_file: str | None = None):
        self.credentials_file = Path(credentials_file)
        self.client_secrets_file = client_secrets_file
        self._creds: Credentials | None = None

    def _load_credentials(self) -> Credentials | None:
        if not self.credentials_file.exists():
            return None
        try:
            return Credentials.from_authorized_user_file(str(self.credentials_file), SCOPES)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load credentials: %s", exc)
            return None

    def _save_credentials(self, creds: Credentials) -> None:
        self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_file.write_text(creds.to_json(), encoding="utf-8")

    def authenticate(self) -> dict[str, Any]:
        """Run OAuth flow and save credentials. Returns status dict."""
        if not self.client_secrets_file or not Path(self.client_secrets_file).exists():
            return {
                "status": "error",
                "message": (
                    "client_secrets_file is required for OAuth. "
                    "Download client_secret.json from Google Cloud Console and set it in config."
                ),
            }

        flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
        creds = flow.run_local_server(port=0)
        self._save_credentials(creds)
        self._creds = creds
        return {"status": "ok", "message": "Google authentication successful."}

    def _ensure_creds(self) -> Credentials:
        if self._creds and self._creds.valid:
            return self._creds
        self._creds = self._load_credentials()
        if self._creds and self._creds.valid:
            return self._creds
        if self._creds and self._creds.expired and self._creds.refresh_token:
            self._creds.refresh(Request())
            self._save_credentials(self._creds)
            return self._creds
        raise RuntimeError("Not authenticated. Run the auth action first.")

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous Google API call in a thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def gmail_list(self, query: str = "", max_results: int = 10) -> dict[str, Any]:
        creds = self._ensure_creds()
        service = build("gmail", "v1", credentials=creds, static_discovery=False)
        result = await self._run_sync(
            service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute
        )
        messages = result.get("messages", [])
        return {"count": len(messages), "messages": messages}

    async def gmail_read(self, message_id: str) -> dict[str, Any]:
        creds = self._ensure_creds()
        service = build("gmail", "v1", credentials=creds, static_discovery=False)
        msg = await self._run_sync(
            service.users().messages().get(userId="me", id=message_id, format="full").execute
        )
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        subject = headers.get("subject", "")
        from_addr = headers.get("from", "")
        date = headers.get("date", "")

        parts = payload.get("parts", [])
        body = ""
        for part in parts:
            if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
                data = part["body"]["data"]
                body = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
                break

        return {
            "id": message_id,
            "subject": subject,
            "from": from_addr,
            "date": date,
            "snippet": msg.get("snippet", ""),
            "body": body,
        }

    async def calendar_list(self, days: int = 7, max_results: int = 10) -> dict[str, Any]:
        creds = self._ensure_creds()
        service = build("calendar", "v3", credentials=creds, static_discovery=False)
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()
        events_result = await self._run_sync(
            service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute
        )
        items = events_result.get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            start_time = start.get("dateTime", start.get("date", ""))
            events.append({
                "id": item.get("id"),
                "summary": item.get("summary", "(No title)"),
                "start": start_time,
                "creator": item.get("creator", {}).get("email", ""),
            })
        return {"count": len(events), "events": events}
