"""
NewsOps Revision 2 - Switch Status & Autonomous Agent Dispatch API Endpoint.

Transparently reports Switch integration status, server health, agent registration,
and provides an endpoint to trigger autonomous Scout -> Analyst -> Editor cycles.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..db.mongodb import get_db
from ..config.settings import settings
from ..switch.protocol import SwitchProtocolClient
from ..switch.orchestrator import SwitchNewsOpsOrchestrator

router = APIRouter(prefix="/switch", tags=["Switch"])


class CycleRequest(BaseModel):
    room_key: str = Field(default="aiml", description="Room key (aiml, cloud, security)")
    auto_approve: bool = Field(default=False, description="Whether to auto-approve digest for demo purposes")
    reviewer: str = Field(default="@operator", description="Reviewer name for approval gate")


class SwitchMessageRequest(BaseModel):
    room_ref: str = Field(..., description="Switch room identifier or slug")
    content: str = Field(..., description="Message text in Markdown")


@router.get("/status", summary="Get Switch integration status")
async def get_switch_status(db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Returns live Switch Agent Protocol integration status:
    - Server URL & configured agent ID
    - Connection state (connected/standby)
    - Latest agent activity timestamp and active agent
    - Capabilities of Scout, Analyst, and Editor
    """
    client = SwitchProtocolClient(
        base_url=settings.SWITCH_BASE_URL,
        agent_id=settings.SWITCH_POSTER_AGENT_ID,
        token=settings.SWITCH_POSTER_TOKEN,
    )
    is_live = await client.connect() if client.is_configured else False
    if is_live:
        await client.disconnect()

    latest_activity = await db.agent_activity.find_one(sort=[("created_at", -1)])
    last_ts = latest_activity.get("created_at") if latest_activity else "never"
    last_agent = latest_activity.get("agent") if latest_activity else "none observed yet"

    return {
        "mode": "switch_agent_protocol_active",
        "message": f"agents call NewsOps via CLI and Switch Agent Protocol; last agent activity at {last_ts}",
        "switch_server_url": settings.SWITCH_BASE_URL or "http://127.0.0.1:55316",
        "connected_to_switch": is_live,
        "poster_agent_id": settings.SWITCH_POSTER_AGENT_ID,
        "is_configured": client.is_configured,
        "last_activity_at": last_ts,
        "last_active_agent": last_agent,
        "agents": {
            "scout": {
                "role": "Scout",
                "capabilities": ["news_discovery", "source_collection", "command_extraction"],
                "status": "ready",
            },
            "analyst": {
                "role": "Analyst",
                "capabilities": ["claim_verification", "evidence_evaluation", "confidence_scoring", "contradiction_detection"],
                "status": "ready",
            },
            "editor": {
                "role": "Editor",
                "capabilities": ["digest_creation", "publication", "approval_workflow"],
                "status": "ready",
                "approval_gate": "403_enforced",
            },
        },
    }


@router.post("/cycle", summary="Execute autonomous Scout -> Analyst -> Editor cycle")
async def trigger_autonomous_cycle(
    payload: CycleRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Executes an autonomous intelligence handoff loop:
    1. Scout gathers candidates
    2. Analyst verifies claims & detects contradictions
    3. Editor compiles draft digest
    4. 403 Approval Gate holds digest (or approves if auto_approve=True)
    5. Delivers intelligence report to configured Switch room
    """
    client = SwitchProtocolClient(
        base_url=settings.SWITCH_BASE_URL,
        agent_id=settings.SWITCH_POSTER_AGENT_ID,
        token=settings.SWITCH_POSTER_TOKEN,
    )
    orchestrator = SwitchNewsOpsOrchestrator(
        api_base=f"http://127.0.0.1:{settings.API_PORT}{settings.API_V1_PREFIX}",
        agent_token=settings.AGENT_API_TOKEN,
        switch_client=client,
    )

    reviewer = payload.reviewer if payload.auto_approve else None
    result = await orchestrator.run_pipeline(
        room_key=payload.room_key,
        auto_approve_reviewer=reviewer,
    )
    return result


@router.post("/message", summary="Send message to Switch room via Agent Protocol")
async def post_switch_message(payload: SwitchMessageRequest):
    """Sends a message to a Switch room via the official Agent Protocol."""
    client = SwitchProtocolClient(
        base_url=settings.SWITCH_BASE_URL,
        agent_id=settings.SWITCH_POSTER_AGENT_ID,
        token=settings.SWITCH_POSTER_TOKEN,
    )
    res = await client.post_message(room_ref=payload.room_ref, text=payload.content)
    return res
