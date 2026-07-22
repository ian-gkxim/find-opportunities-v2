"""Gmail API integration client for sending emails.

Provides an async interface for sending emails via the Gmail API using
OAuth2 credentials (refresh token flow). Used as the Send_Channel for
direct email outreach (as opposed to Lemlist sequence enrollment).
"""

import base64
import logging
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

logger = logging.getLogger(__name__)


# --- Data Models ---


@dataclass
class EmailMessage:
    """An email message ready to send via Gmail API."""

    to: str
    subject: str
    body_html: str
    from_email: str | None = None  # Uses authenticated user if None
    reply_to: str | None = None


@dataclass
class GmailSendResult:
    """Result of a Gmail send operation."""

    message_id: str
    thread_id: str
    label_ids: list[str]


# --- Gmail Client ---


class GmailClient:
    """Async client for sending emails via the Gmail API.

    Uses OAuth2 refresh token flow to obtain access tokens, then sends
    emails via the Gmail messages.send endpoint.

    This client handles:
    - Token refresh via Google OAuth2 token endpoint
    - Email composition (MIME multipart)
    - Sending via Gmail API v1
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._http_client = http_client
        self._access_token: str | None = None

    async def _get_access_token(self) -> str:
        """Refresh the OAuth2 access token using the refresh token."""
        if self._access_token:
            return self._access_token

        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            return self._access_token
        finally:
            if not self._http_client:
                await client.aclose()

    async def send_email(self, message: EmailMessage) -> GmailSendResult:
        """Send an email via the Gmail API.

        Args:
            message: The email message to send.

        Returns:
            GmailSendResult with message_id and thread_id from Gmail.

        Raises:
            httpx.HTTPStatusError: If the Gmail API returns an error.
        """
        access_token = await self._get_access_token()

        # Build MIME message
        mime_msg = MIMEMultipart("alternative")
        mime_msg["To"] = message.to
        mime_msg["Subject"] = message.subject
        if message.from_email:
            mime_msg["From"] = message.from_email
        if message.reply_to:
            mime_msg["Reply-To"] = message.reply_to

        mime_msg.attach(MIMEText(message.body_html, "html"))

        # Encode to base64url
        raw_message = base64.urlsafe_b64encode(
            mime_msg.as_bytes()
        ).decode("utf-8")

        # Send via Gmail API
        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(
                self.SEND_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw_message},
            )
            response.raise_for_status()
            data = response.json()

            result = GmailSendResult(
                message_id=data.get("id", ""),
                thread_id=data.get("threadId", ""),
                label_ids=data.get("labelIds", []),
            )

            logger.info(
                "Gmail email sent successfully: message_id=%s, to=%s",
                result.message_id,
                message.to,
            )
            return result
        finally:
            if not self._http_client:
                await client.aclose()
