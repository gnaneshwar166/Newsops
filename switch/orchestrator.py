"""
NewsOps Revision 2 - Switch Autonomous Pipeline Orchestrator.

Implements the complete multi-agent workflow:
1. Scout: Discovers raw news & tool releases.
2. AI Engine: Normalizes, deduplicates, and ranks stories.
3. Analyst: Extracts claims, assesses evidence, calculates confidence.
4. Editor: Compiles verified intelligence digest.
5. Approval Gate: Checks human editorial approval.
6. Publication: Delivers approved digest to Switch rooms.
"""

import asyncio
from typing import Any, Dict, List, Optional
import httpx

from ..core.logging import logger
from .protocol import SwitchProtocolClient
from .agents.scout import ScoutAgent
from .agents.analyst import AnalystSwitchAgent
from .agents.editor import EditorAgent


class SwitchNewsOpsOrchestrator:
    """
    Coordinates the autonomous handoff between Scout, Analyst, and Editor agents,
    delivering verified developer intelligence into configured Switch rooms.
    """

    def __init__(
        self,
        api_base: str = "http://localhost:8000/api/v1",
        agent_token: str = "dev-agent-secret-token-change-me",
        switch_client: Optional[SwitchProtocolClient] = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.agent_token = agent_token
        self.switch_client = switch_client

        # Initialize the 3 agents
        self.scout = ScoutAgent(api_base=self.api_base, agent_token=self.agent_token, switch_client=self.switch_client)
        self.analyst = AnalystSwitchAgent(api_base=self.api_base, agent_token=self.agent_token, switch_client=self.switch_client)
        self.editor = EditorAgent(api_base=self.api_base, agent_token=self.agent_token, switch_client=self.switch_client)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.agent_token}",
            "Content-Type": "application/json",
        }

    async def run_pipeline(
        self,
        room_key: str,
        auto_approve_reviewer: Optional[str] = None,
        switch_room_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the end-to-end autonomous intelligence loop:
        Scout -> Analyst -> Editor -> Approval -> Publication.
        """
        room_ref = switch_room_ref or f"switch:room:{room_key}"
        logger.info(f"Starting NewsOps autonomous pipeline for room #{room_key}...")

        # -------------------------------------------------------------
        # STEP 1: SCOUT DISCOVERY
        # -------------------------------------------------------------
        logger.info("[Pipeline Step 1/5] Scout discovering candidates...")
        scout_res = await self.scout.run(room_key=room_key, switch_room_ref=room_ref)
        story_ids = scout_res.get("top_story_ids", [])
        logger.info(f"Scout found {len(story_ids)} high-priority candidate stories.")

        # -------------------------------------------------------------
        # STEP 2: ANALYST VERIFICATION & CLAIM EXTRACTION
        # -------------------------------------------------------------
        logger.info(f"[Pipeline Step 2/5] Analyst verifying {len(story_ids)} stories...")
        analyst_results = []
        for sid in story_ids[:3]:  # Top 3 stories
            res = await self.analyst.analyze_story_id(story_id=sid, switch_room_ref=room_ref)
            analyst_results.append(res)
        logger.info(f"Analyst completed verification for {len(analyst_results)} stories.")

        # -------------------------------------------------------------
        # STEP 3: EDITOR DRAFT COMPILATION
        # -------------------------------------------------------------
        logger.info(f"[Pipeline Step 3/5] Editor compiling draft digest for #{room_key}...")
        digest_id = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                d_res = await client.post(
                    f"{self.api_base}/agent/digests",
                    json={"room_key": room_key, "story_ids": story_ids[:5]},
                    headers=self._headers(),
                )
                if d_res.status_code in (200, 201):
                    digest_data = d_res.json()
                    digest_id = digest_data.get("_id") or digest_data.get("id")
        except Exception as e:
            logger.warning(f"Editor digest creation warning: {e}")

        # -------------------------------------------------------------
        # STEP 4: APPROVAL GATE CHECK
        # -------------------------------------------------------------
        approval_status = "pending_human_review"
        if digest_id and auto_approve_reviewer:
            logger.info(f"[Pipeline Step 4/5] Recording editorial decision by {auto_approve_reviewer}...")
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    dec_res = await client.post(
                        f"{self.api_base}/agent/digests/{digest_id}/decision",
                        json={"decision": "approve", "by": auto_approve_reviewer},
                        headers=self._headers(),
                    )
                    if dec_res.status_code in (200, 201):
                        approval_status = "approved"
            except Exception as e:
                logger.warning(f"Decision submission error: {e}")
        else:
            logger.info("[Pipeline Step 4/5] Approval gate: Digest held for human approval (403 gate active).")

        # -------------------------------------------------------------
        # STEP 5: PUBLICATION & SWITCH ROOM BROADCAST
        # -------------------------------------------------------------
        publish_res = None
        if digest_id:
            logger.info(f"[Pipeline Step 5/5] Editor executing publication check for digest `{digest_id}`...")
            publish_res = await self.editor.run(digest_id=digest_id, switch_room_ref=room_ref)

        summary = {
            "room_key": room_key,
            "scout_candidates": len(story_ids),
            "analyst_verified": len(analyst_results),
            "digest_id": digest_id,
            "approval_status": approval_status,
            "publish_result": publish_res,
            "status": "completed",
        }
        logger.info(f"Pipeline finished for #{room_key}: status={summary['status']}")
        return summary
