"""
Comprehensive Test Suite for Switch Agent Protocol Integration.

Verifies:
- Official Agent Protocol HTTP operations (typing, status, history, subscribe)
- Interactive @mention handling by Scout, Analyst, Editor
- Multi-agent handoff mechanics
- 403 publish gate enforcement in Editor
- Autonomous pipeline cycle execution
"""

import pytest
from unittest.mock import AsyncMock, patch
from newsops.switch.protocol import SwitchProtocolClient, ConnectionState, AgentRegistration
from newsops.switch.agents.scout import ScoutAgent
from newsops.switch.agents.analyst import AnalystSwitchAgent
from newsops.switch.agents.editor import EditorAgent
from newsops.switch.daemon import run_autonomous_cycle


@pytest.mark.anyio
async def test_protocol_typing_and_status():
    client = SwitchProtocolClient()
    # Unconfigured should operate safely without crashing
    assert await client.set_typing("room-aiml", True) is True
    assert await client.update_status("analyzing") is True


@pytest.mark.anyio
async def test_protocol_room_subscription_and_ops():
    client = SwitchProtocolClient()
    assert await client.subscribe_room("room-cloud") is True
    assert "room-cloud" in client.subscribed_rooms
    ops = await client.discover_operations()
    assert "post_message" in ops


@pytest.mark.anyio
async def test_scout_interactive_mention_handler():
    scout = ScoutAgent(api_base="http://127.0.0.1:8000/api/v1")
    reply = await scout.handle_message("switch:room:aiml", "@scout discover aiml", sender="@alice")
    assert reply is not None
    assert "Scout" in reply


@pytest.mark.anyio
async def test_analyst_interactive_mention_handler():
    analyst = AnalystSwitchAgent(api_base="http://127.0.0.1:8000/api/v1")
    # Missing ID prompt
    reply_missing = await analyst.handle_message("switch:room:aiml", "@analyst check", sender="@alice")
    assert "Please provide a story ID" in reply_missing

    # Mock get_story for offline testing
    mock_story = {
        "_id": "story-aiml-001",
        "title": "vLLM v0.6.4: Speculative Decoding Released",
        "room_key": "aiml",
        "members": [{"title": "vLLM Release Notes", "publisher": "GitHub"}],
    }
    with patch.object(analyst, "get_story", new=AsyncMock(return_value=mock_story)):
        with patch.object(analyst, "submit_analysis", new=AsyncMock(return_value={"status": "created"})):
            reply_valid = await analyst.handle_message("switch:room:aiml", "@analyst verify story-aiml-001", sender="@alice")
            assert "Analyst Verification Report" in reply_valid
            assert "Handoff" in reply_valid


@pytest.mark.anyio
async def test_editor_interactive_approval_flow():
    editor = EditorAgent(api_base="http://127.0.0.1:8000/api/v1")

    # Check help response
    help_reply = await editor.handle_message("switch:room:aiml", "@editor help", sender="@alice")
    assert "NewsOps Editor Available Commands" in help_reply

    # Check publication gate on unapproved digest
    with patch.object(editor, "attempt_publish", new=AsyncMock(return_value={"status": "blocked", "code": 403})):
        gate_reply = await editor.handle_message("switch:room:aiml", "@editor publish dig-unapproved-999", sender="@alice")
        assert "Publication Gate" in gate_reply or "403 Forbidden" in gate_reply


@pytest.mark.anyio
async def test_autonomous_cycle_runner_aiml():
    result = await run_autonomous_cycle(room_key="aiml", auto_approve=True, reviewer="@gnaneshwar")
    assert result["room_key"] == "aiml"
    assert result["status"] == "completed"
    assert result["scout_candidates"] >= 0
    assert result["analyst_verified"] >= 0
