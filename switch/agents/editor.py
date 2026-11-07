"""
NewsOps Revision 2 - Editor Agent (Switch Agent Protocol Worker).

Curates verified developer intelligence digests, presents summaries for human review,
and enforces the 403 approval gate before publication.
Publishes directly to configured Switch rooms once approved.
"""

from typing import Any, Dict, List, Optional
import httpx

from ...core.logging import logger
from ..protocol import SwitchProtocolClient


class EditorAgent:
    name = "editor"
    display_name = "NewsOps Editor"
    description = "Curates verified developer intelligence digests and controls publication subject to human editorial approval."
    capabilities = ["digest_creation", "editorial_summary", "publication", "approval_workflow"]

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

    async def get_digest(self, digest_id: str) -> Optional[dict]:
        """Fetches digest details including stories, items, and status."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.api_base}/digests/{digest_id}", headers=self._headers())
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            logger.warning(f"Editor get_digest warning: {e}")
        return None

    async def compile_digest(self, room_key: str, story_ids: List[str]) -> Optional[dict]:
        """Compiles candidate stories into a draft digest."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.api_base}/agent/digests",
                    json={"room_key": room_key, "story_ids": story_ids},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
        except Exception as e:
            logger.warning(f"Editor compile_digest error: {e}")
        return None

    async def submit_approval_decision(self, digest_id: str, decision: str, reviewer: str) -> dict:
        """Records human reviewer approval/rejection."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.api_base}/agent/digests/{digest_id}/decision",
                    json={"decision": decision, "by": reviewer},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
                return {"status": "error", "code": res.status_code, "detail": res.text}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def attempt_publish(self, digest_id: str) -> dict:
        """
        Attempts to publish a digest.
        Strictly enforces the 403 Forbidden gate if unapproved!
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(f"{self.api_base}/digests/{digest_id}/publish", headers=self._headers())
                if res.status_code == 403:
                    return {"status": "blocked", "reason": "approval_required", "code": 403}
                if res.status_code == 200:
                    return {"status": "published", **res.json()}
                return {"status": "error", "code": res.status_code}
        except Exception as e:
            logger.warning(f"Editor attempt_publish warning: {e}")
            return {"status": "error", "error": str(e)}

    async def handle_message(self, room_ref: str, message_text: str, sender: str = "") -> Optional[str]:
        """
        Interactive command handler for Switch room messages addressing @editor.
        Commands:
        - `@editor approve <digest_id>`
        - `@editor reject <digest_id>`
        - `@editor publish <digest_id>`
        - `@editor digest <room>`
        """
        text_lower = message_text.lower()
        words = message_text.split()

        # Find digest_id
        digest_id = None
        for w in words:
            if "dig-" in w:
                digest_id = w.strip("`'\",")
                break

        if ("approve" in words or "@editor approve" in text_lower) and "unapproved" not in text_lower and digest_id:
            reviewer = sender or "@operator"
            dec_res = await self.submit_approval_decision(digest_id, "approve", reviewer)
            pub_res = await self.attempt_publish(digest_id)

            if pub_res.get("status") == "published":
                reply = (
                    f"🎉 **Editor**: Digest `{digest_id}` was **APPROVED** by {reviewer} and successfully **PUBLISHED**!\n"
                    f"Delivered to subscribers of #{pub_res.get('room_key', room_ref)}."
                )
            else:
                reply = f"✅ **Editor**: Decision recorded for `{digest_id}`: approved. Publish status: {pub_res.get('status')}."

        elif "reject" in text_lower and digest_id:
            reviewer = sender or "@operator"
            await self.submit_approval_decision(digest_id, "reject", reviewer)
            reply = f"❌ **Editor**: Digest `{digest_id}` was **REJECTED** by {reviewer}. It will not be published."

        elif "publish" in text_lower and digest_id:
            pub_res = await self.attempt_publish(digest_id)
            if pub_res.get("status") == "blocked":
                reply = (
                    f"🛑 **Publication Gate (403 Forbidden)**: Digest `{digest_id}` is NOT approved yet!\n"
                    f"To approve, reply: `@editor approve {digest_id}`"
                )
            elif pub_res.get("status") == "published":
                reply = f"🚀 **Editor**: Digest `{digest_id}` is now LIVE and published!"
            else:
                reply = f"Editor publish response: {pub_res}"
        else:
            reply = (
                "📰 **NewsOps Editor Available Commands**:\n"
                "- `@editor digest aiml` — Curates a draft digest\n"
                "- `@editor approve <digest_id>` — Approves and publishes verified digest\n"
                "- `@editor reject <digest_id>` — Rejects digest draft\n"
                "- `@editor publish <digest_id>` — Verifies 403 approval gate"
            )

        if self.switch_client:
            await self.switch_client.post_message(room_ref, reply)

        return reply

    async def run(self, digest_id: str, switch_room_ref: str = "") -> dict:
        """Automated editorial publication check."""
        digest = await self.get_digest(digest_id)
        if not digest:
            return {"status": "not_found", "digest_id": digest_id}

        result = await self.attempt_publish(digest_id)
        current_status = digest.get("status")

        if result.get("status") == "published":
            summary = (
                f"🚀 **Editor**: Digest `{digest_id}` published successfully to #{digest.get('room_key')}.\n"
                f"Verified developer intelligence is now live."
            )
        elif result.get("status") == "blocked":
            summary = (
                f"🛑 **Editor**: Digest `{digest_id}` is in `{current_status}` status and requires human approval.\n"
                f"Use `@editor approve {digest_id}` to authorize publication."
            )
        else:
            summary = f"Editor publish check for `{digest_id}` returned `{result.get('status')}`."

        if self.switch_client and switch_room_ref:
            await self.switch_client.post_message(switch_room_ref, summary)

        return {
            "digest_id": digest_id,
            "digest_status": current_status,
            "publish_result": result,
            "summary": summary,
        }
