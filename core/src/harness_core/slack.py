"""Cliente mínimo da Web API do Slack para o bot da MÊTIS.

O aviso no iPhone sai de um bot (app do Slack) porque o Slack não notifica mensagem que a
própria pessoa manda. O bot conversa com o Pedro numa DM; lembrete com hora marcada é
agendado no Slack (chat.scheduleMessage), então chega mesmo com o Mac dormindo.
"""

from __future__ import annotations

from datetime import datetime

import httpx

API = "https://slack.com/api"

# Manifesto do app: o Pedro cola em api.slack.com/apps → Create New App → From a manifest.
MANIFEST = """display_information:
  name: MÊTIS
  description: Avisos e lembretes da MÊTIS, o ambiente pessoal do Pedro no Mac.
  background_color: "#1f2330"
features:
  bot_user:
    display_name: MÊTIS
    always_online: true
oauth_config:
  scopes:
    bot:
      - chat:write
      - im:write
      - users:read
      - users:read.email
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
"""


class SlackError(RuntimeError):
    pass


class Slack:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token
        self.client = client or httpx.Client(timeout=15)

    def call(self, method: str, **params) -> dict:
        response = self.client.post(
            f"{API}/{method}",
            headers={"Authorization": f"Bearer {self.token}"},
            data={k: v for k, v in params.items() if v is not None},
        )
        data = response.json()
        if not data.get("ok"):
            raise SlackError(f"Slack recusou {method}: {data.get('error', response.status_code)}")
        return data

    def identity(self) -> dict:
        """Workspace e nome do bot (auth.test)."""
        data = self.call("auth.test")
        return {"team": data.get("team", ""), "team_id": data.get("team_id", ""), "bot": data.get("user", ""), "url": data.get("url", "")}

    def user_by_email(self, email: str) -> dict:
        data = self.call("users.lookupByEmail", email=email)
        user = data["user"]
        return {"id": user["id"], "name": user.get("real_name") or user.get("name", ""), "tz": user.get("tz", "")}

    def dm(self, user_id: str) -> str:
        """Canal da conversa privada entre o bot e a pessoa."""
        return self.call("conversations.open", users=user_id)["channel"]["id"]

    def send(self, channel: str, text: str) -> dict:
        data = self.call("chat.postMessage", channel=channel, text=text)
        return {"channel": data["channel"], "ts": data["ts"]}

    def schedule(self, channel: str, text: str, when: datetime) -> dict:
        if when.tzinfo is None:
            when = when.astimezone()
        data = self.call("chat.scheduleMessage", channel=channel, text=text, post_at=str(int(when.timestamp())))
        return {"channel": data["channel"], "id": data["scheduled_message_id"], "post_at": data["post_at"]}
