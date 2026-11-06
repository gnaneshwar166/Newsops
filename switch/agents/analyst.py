"""
NewsOps Revision 2 - Analyst Agent (Switch Agent Protocol Worker).

Evaluates claims, examines source credibility, detects contradictions,
and submits structured verification payloads to NewsOps backend.
Posts verification reports to Switch rooms and hands off to Editor.
"""

from typing import Any, Dict, List, Optional
import httpx

from ...ai.analyst import analyst_agent
from ...core.logging import logger
from ..protocol import SwitchProtocolClient


class AnalystSwitchAgent:
    name = "analyst"
    display_name = "NewsOps Analyst"
    description = "Verifies claims, evaluates primary source evidence, identifies contradictions, and calculates confidence scores."
    capabilities = ["claim_verification", "evidence_evaluation", "confidence_scoring", "contradiction_detection"]

    def __init__(
        self,
        api_base: str = "http://localhost:8000/api/v1",
        agent_token: str = "dev-agent-secret-token-change-me",
        switch_client: Optional[SwitchProtocolClient] = None,
        timeout: float = 45.0,
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

    async def get_story(self, story_id: str) -> Optional[dict]:
        """Fetches full story details including claims and evidence."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.api_base}/stories/{story_id}", headers=self._headers())
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            logger.warning(f"Analyst get_story warning: {e}")
        return None

    async def log_activity(self, room_key: str, action: str, message: str, story_id: Optional[str] = None) -> dict:
        """Logs analyst activity to NewsOps backend audit trail."""
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
            logger.warning(f"Analyst log_activity warning: {e}")
        return {"status": "error"}

    async def submit_analysis(self, story_id: str, payload: dict) -> dict:
        """Submits verified analysis payload to NewsOps backend."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.api_base}/agent/stories/{story_id}/analysis",
                    json=payload,
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
        except Exception as e:
            logger.warning(f"Analyst submit_analysis warning: {e}")
        return {"status": "error"}

    async def analyze_story_id(self, story_id: str, switch_room_ref: str = "") -> dict:
        """Runs claim extraction, evidence evaluation, and contradiction checks."""
        story = await self.get_story(story_id)
        if not story:
            return {"status": "not_found", "story_id": story_id}

        title = story.get("title", "")
        members = story.get("members", [])
        text = " ".join([str(m.get("title", "")) for m in members]) or title

        # Execute AI Verification Engine
        submission = analyst_agent.analyze_story(
            story_id=story_id,
            title=title,
            text=text,
            analyst_id=self.name,
        )

        # Submit verification payload to backend
        res = await self.submit_analysis(story_id, submission.model_dump(mode="json"))

        confidence_pct = int(submission.overall_confidence * 100)
        claims_cnt = len(submission.claims)
        contradictions = [r for r in getattr(submission, "verification_results", []) if str(getattr(r, "status", "")).lower() == "contradicted"]

        status_icon = "✅" if not contradictions and submission.overall_confidence >= 0.7 else "⚠️"
        summary = (
            f"{status_icon} **Analyst Verification Report** | Story: `{story_id}`\n\n"
            f"**Title**: {title}\n"
            f"- **Claims Verified**: {claims_cnt}\n"
            f"- **Confidence**: **{confidence_pct}%**\n"
            f"- **Contradictions**: {len(contradictions)}\n"
        )
        if contradictions:
            summary += f"- **Flagged Claims**: {contradictions[0].claim_text}\n"

        await self.log_activity(
            room_key=story.get("room_key", "general"),
            action="verify_story",
            message=f"Verified story {story_id}: {claims_cnt} claims, {confidence_pct}% confidence",
            story_id=story_id,
        )

        if self.switch_client and switch_room_ref:
            await self.switch_client.post_message(switch_room_ref, summary)

        return {
            "story_id": story_id,
            "claims": claims_cnt,
            "confidence": submission.overall_confidence,
            "contradictions": len(contradictions),
            "api_status": res.get("status"),
            "summary": summary,
        }

    async def handle_message(self, room_ref: str, message_text: str, sender: str = "") -> Optional[str]:
        """
        Interactive command handler for Switch room messages addressing @analyst.
        Commands:
        - `@analyst verify <story_id>`
        - `@analyst check <claim>`
        """
        words = message_text.split()
        story_id = None
        for w in words:
            if "story-" in w or len(w) > 8 and not w.startswith("@"):
                story_id = w.strip("`'\",")
                break

        if not story_id:
            reply = "🔍 **Analyst**: Please provide a story ID to verify (e.g. `@analyst verify story-aiml-001`)."
        else:
            if self.switch_client:
                await self.switch_client.set_typing(room_ref, True)
            res = await self.analyze_story_id(story_id, switch_room_ref="")
            reply = res.get("summary", f"Analyst could not verify {story_id}.")
            reply += f"\n\n👉 **Handoff**: Passing verified intelligence to `@editor` for digest inclusion."

        if self.switch_client:
            await self.switch_client.set_typing(room_ref, False)
            await self.switch_client.post_message(room_ref, reply)

        return reply
