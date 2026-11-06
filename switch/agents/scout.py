"""
NewsOps Revision 2 - Scout Agent (Switch Agent Protocol Worker).

Discovers emerging developer releases, tools, and vulnerabilities.
Normalizes, deduplicates, and extracts tools and commands.
Posts rich structured findings to Switch rooms and hands off to Analyst.
"""

from typing import Any, Dict, List, Optional
import httpx

from ...core.logging import logger
from ..protocol import SwitchProtocolClient


class ScoutAgent:
    name = "scout"
    display_name = "NewsOps Scout"
    description = "Discovers and collects relevant news stories, tool releases, and CVE advisories."
    capabilities = ["news_discovery", "source_collection", "trend_identification", "command_extraction"]

    def __init__(
        self,
        api_base: str = "http://localhost:8000/api/v1",
        agent_token: str = "dev-agent-secret-token-change-me",
        switch_client: Optional[SwitchProtocolClient] = None,
        timeout: float = 30.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.agent_token = agent_token
        self.switch_client = switch_client
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.agent_token}",
            "Content-Type": "application/json",
        }

    async def discover_candidates(self, room_key: str, topics: List[str] = None, limit: int = 15) -> List[dict]:
        """Queries the NewsOps backend for newly ingested candidates."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                params = {"limit": limit}
                if topics:
                    params["topic"] = topics[0]
                res = await client.get(f"{self.api_base}/stories", params=params, headers=self._headers())
                if res.status_code == 200:
                    data = res.json()
                    return data.get("items", []) if isinstance(data, dict) else data
        except Exception as e:
            logger.warning(f"Scout discover_candidates warning: {e}")
        return []

    async def log_activity(self, room_key: str, action: str, message: str, story_id: Optional[str] = None) -> dict:
        """Logs agent activity to NewsOps backend audit trail."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.api_base}/agent/activity",
                    json={
                        "agent": self.name,
                        "room": room_key,
                        "action": action,
                        "message": message,
                        "story_id": story_id,
                    },
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
        except Exception as e:
            logger.warning(f"Scout log_activity warning: {e}")
        return {"status": "error"}

    async def handle_message(self, room_ref: str, message_text: str, sender: str = "") -> Optional[str]:
        """
        Interactive command handler for Switch room messages addressing @scout.
        Commands supported:
        - `@scout discover <room>`
        - `@scout scan`
        - `@scout sources`
        """
        room_key = "aiml"
        for k in ["cloud", "security", "aiml"]:
            if k in message_text.lower():
                room_key = k
                break

        if self.switch_client:
            await self.switch_client.set_typing(room_ref, True)

        candidates = await self.discover_candidates(room_key, limit=5)
        await self.log_activity(room_key, "discovery", f"Scout discovered {len(candidates)} stories via chat trigger")

        if not candidates:
            reply = f"🔍 **Scout**: Checked sources for #{room_key}, no new unverified items found."
        else:
            story_lines = []
            for c in candidates[:3]:
                title = c.get("title", "Untitled")
                cmd = c.get("install_command")
                cmd_str = f" | `{cmd}`" if cmd else ""
                badge = c.get("trust_badge", "primary")
                story_lines.append(f"- **{title}** [{badge}]{cmd_str}")

            top_ids = [c.get("_id") or c.get("id") for c in candidates[:3]]
            reply = (
                f"📡 **Scout Discovery Report** | #{room_key}\n\n"
                f"Discovered **{len(candidates)}** candidate stories:\n"
                + "\n".join(story_lines)
                + f"\n\n👉 **Handoff**: Passing top items `{top_ids}` to `@analyst` for claim verification."
            )

        if self.switch_client:
            await self.switch_client.set_typing(room_ref, False)
            await self.switch_client.post_message(room_ref, reply)

        return reply

    async def run(self, room_key: str, topics: List[str] = None, switch_room_ref: str = "") -> dict:
        """Scheduled / automated discovery cycle."""
        topics = topics or [room_key]
        candidates = await self.discover_candidates(room_key, topics, limit=8)
        top_ids = [c.get("_id") or c.get("id") for c in candidates[:5]]

        summary = (
            f"📡 **Scout Report** | Room: `#{room_key}`\n"
            f"Collected **{len(candidates)}** normalized & deduplicated candidates.\n"
            f"Handing off to `@analyst` for primary source & contradiction analysis."
        )

        await self.log_activity(room_key, "cycle_complete", summary)

        if self.switch_client and switch_room_ref:
            await self.switch_client.post_message(switch_room_ref, summary)

        return {
            "room_key": room_key,
            "candidates_found": len(candidates),
            "top_story_ids": top_ids,
            "summary": summary,
        }
