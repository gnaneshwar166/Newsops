"""
NewsOps Revision 2 - Switch Multi-Agent Runtime Daemon & Dispatcher.

Runs Scout, Analyst, and Editor as active Switch Agent Protocol workers.
Can run in two modes:
1. `listen`: Opens WebSocket connections to Switch server, listening for @mentions in rooms.
2. `cycle`: Runs an autonomous discovery -> verification -> curation -> approval gate cycle.
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

from ..core.logging import logger
from .protocol import SwitchProtocolClient
from .orchestrator import SwitchNewsOpsOrchestrator
from .agents.scout import ScoutAgent
from .agents.analyst import AnalystSwitchAgent
from .agents.editor import EditorAgent

SWITCH_BASE_URL = os.getenv("SWITCH_BASE_URL", "http://127.0.0.1:55316").rstrip("/")
SWITCH_POSTER_AGENT_ID = os.getenv("SWITCH_POSTER_AGENT_ID", "newsops-scout")
SWITCH_POSTER_TOKEN = os.getenv("SWITCH_POSTER_TOKEN", "")
NEWSOPS_API = os.getenv("NEWSOPS_API", "http://localhost:8000/api/v1")
AGENT_API_TOKEN = os.getenv("AGENT_API_TOKEN", "dev-agent-secret-token-change-me")


async def run_autonomous_cycle(room_key: str = "aiml", auto_approve: bool = False, reviewer: str = "@gnaneshwar"):
    """Executes a complete autonomous cycle across the 3 agents."""
    client = SwitchProtocolClient(
        base_url=SWITCH_BASE_URL,
        agent_id=SWITCH_POSTER_AGENT_ID,
        token=SWITCH_POSTER_TOKEN,
    )
    connected = await client.connect()
    if connected:
        logger.info(f"Connected to Switch server on {SWITCH_BASE_URL}")
    else:
        logger.info("Operating in simulation mode (Switch connection standby).")

    orchestrator = SwitchNewsOpsOrchestrator(
        api_base=NEWSOPS_API,
        agent_token=AGENT_API_TOKEN,
        switch_client=client,
    )

    reviewer_val = reviewer if auto_approve else None
    result = await orchestrator.run_pipeline(room_key=room_key, auto_approve_reviewer=reviewer_val)

    print("\n" + "=" * 60)
    print("NEWSOPS × SWITCH — AUTONOMOUS PIPELINE EXECUTION COMPLETE")
    print("=" * 60)
    print(f"Room: #{result['room_key']}")
    print(f"Candidates Discovered by Scout: {result['scout_candidates']}")
    print(f"Stories Verified by Analyst: {result['analyst_verified']}")
    print(f"Digest ID Created by Editor: {result['digest_id']}")
    print(f"Human Approval Gate Status: {result['approval_status']}")
    print(f"Publication Result: {result['publish_result']}")
    print("=" * 60 + "\n")

    await client.disconnect()
    return result


async def run_listener_daemon():
    """Listens on Switch WebSocket for interactive @mentions."""
    client = SwitchProtocolClient(
        base_url=SWITCH_BASE_URL,
        agent_id=SWITCH_POSTER_AGENT_ID,
        token=SWITCH_POSTER_TOKEN,
    )
    connected = await client.connect()
    if not connected:
        logger.warning(f"Could not connect to Switch at {SWITCH_BASE_URL}. Check if Switch server is running.")

    scout = ScoutAgent(api_base=NEWSOPS_API, agent_token=AGENT_API_TOKEN, switch_client=client)
    analyst = AnalystSwitchAgent(api_base=NEWSOPS_API, agent_token=AGENT_API_TOKEN, switch_client=client)
    editor = EditorAgent(api_base=NEWSOPS_API, agent_token=AGENT_API_TOKEN, switch_client=client)

    async def on_message(msg: dict):
        text = msg.get("content", "") or msg.get("text", "")
        room_id = msg.get("room_id", "aiml")
        sender = msg.get("sender", "@user")
        logger.info(f"Switch room message received: {text[:60]}")

        text_lower = text.lower()
        if "@scout" in text_lower:
            await scout.handle_message(room_id, text, sender)
        elif "@analyst" in text_lower:
            await analyst.handle_message(room_id, text, sender)
        elif "@editor" in text_lower:
            await editor.handle_message(room_id, text, sender)

    client.on("message", on_message)
    await client.start_websocket_listener()
    logger.info("NewsOps Switch Agents are now live and listening for messages... Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1.0)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="NewsOps Switch Multi-Agent Daemon")
    parser.add_argument("--mode", choices=["cycle", "listen"], default="cycle", help="Execution mode")
    parser.add_argument("--room", default="aiml", help="Target room (aiml, cloud, security)")
    parser.add_argument("--approve", action="store_true", help="Auto-approve digest for full publication demo")
    parser.add_argument("--reviewer", default="@gnaneshwar", help="Reviewer username for approval gate")

    args = parser.parse_args()
    if args.mode == "cycle":
        asyncio.run(run_autonomous_cycle(room_key=args.room, auto_approve=args.approve, reviewer=args.reviewer))
    elif args.mode == "listen":
        asyncio.run(run_listener_daemon())


if __name__ == "__main__":
    main()
