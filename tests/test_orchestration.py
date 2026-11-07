"""
Unit & Workflow Tests for Switch Autonomous Pipeline Orchestrator.
"""

import pytest
from newsops.switch.orchestrator import SwitchNewsOpsOrchestrator
from newsops.switch.protocol import SwitchProtocolClient


@pytest.mark.anyio
async def test_orchestrator_initialization():
    orchestrator = SwitchNewsOpsOrchestrator()
    assert orchestrator.scout.name == "scout"
    assert orchestrator.analyst.name == "analyst"
    assert orchestrator.editor.name == "editor"


@pytest.mark.anyio
async def test_orchestrator_run_pipeline_unapproved():
    orchestrator = SwitchNewsOpsOrchestrator(
        api_base="http://127.0.0.1:8000/api/v1",
        agent_token="dev-agent-secret-token-change-me",
    )
    # Run pipeline without auto-approve
    res = await orchestrator.run_pipeline("aiml")
    assert res["room_key"] == "aiml"
    assert res["status"] == "completed"
    assert res["approval_status"] == "pending_human_review"
    assert "scout_candidates" in res


@pytest.mark.anyio
async def test_orchestrator_with_stub_switch_client():
    client = SwitchProtocolClient()
    orchestrator = SwitchNewsOpsOrchestrator(switch_client=client)
    res = await orchestrator.run_pipeline("cloud", auto_approve_reviewer="@alice")
    assert res["room_key"] == "cloud"
    assert res["status"] == "completed"
