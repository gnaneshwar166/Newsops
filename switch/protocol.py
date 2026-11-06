"""
NewsOps Revision 2 - Switch Agent Protocol Client.

Implements HTTP operations and event dispatching according to the official
Switch Agent Protocol (https://docs.switchagents.ai/switch-rooms/internals/agent-protocol).

Handles connection state, credentials check, WebSocket liveness, and clean error reporting.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Callable, Dict, List, Optional
import httpx

try:
    import websockets
except ImportError:
    websockets = None

from ..core.logging import logger


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class AgentRegistration:
    agent_id: str
    name: str
    description: str
    capabilities: List[str] = field(default_factory=list)


class SwitchProtocolClient:
    """
    Official Switch Agent Protocol Client.
    Supports HTTP ops and WebSocket event streaming with ping/pong keepalive.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.agent_id = agent_id or ""
        self.token = token or ""
        self.timeout = timeout
        self.state = ConnectionState.DISCONNECTED
        self.connection_id: Optional[str] = None
        self._handlers: Dict[str, List[Callable]] = {}
        self.is_configured = bool(self.base_url and self.agent_id and self.token)
        self._ws_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Agent-ID": self.agent_id,
        }

    def on(self, event_type: str, handler: Callable):
        """Register an event listener (e.g. 'message', 'ping', 'connected')."""
        self._handlers.setdefault(event_type, []).append(handler)

    async def _emit(self, event_type: str, data: Any):
        for handler in self._handlers.get(event_type, []):
            try:
                res = handler(data)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning(f"Error in Switch event handler ({event_type}): {e}")

    async def connect(self) -> bool:
        """Verifies credentials against Switch server health or agent status."""
        if not self.is_configured:
            logger.info("SwitchProtocolClient: Credentials not configured. Operating in stub/standby mode.")
            self.state = ConnectionState.DISCONNECTED
            return False

        self.state = ConnectionState.CONNECTING
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/health", headers=self._headers())
                if res.status_code == 404:
                    # Some Switch versions use root or /agents/{id}
                    res = await client.get(f"{self.base_url}/", headers=self._headers())
                res.raise_for_status()

            self.state = ConnectionState.CONNECTED
            self.connection_id = f"conn-{self.agent_id}-{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(f"Connected to Switch platform (conn: {self.connection_id})")
            await self._emit("connected", {"connection_id": self.connection_id})
            return True
        except Exception as e:
            self.state = ConnectionState.ERROR
            logger.warning(f"Switch connection attempt failed: {e}")
            return False

    async def disconnect(self):
        """Cleanly disconnects HTTP and WebSocket sessions."""
        self._stop_event.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self.state = ConnectionState.DISCONNECTED
        self.connection_id = None
        await self._emit("disconnected", {})

    async def register_agent(self, registration: AgentRegistration) -> dict:
        """Registers agent once with Switch according to Agent Protocol."""
        if not self.is_configured:
            return {"status": "pending_credentials", "agent_id": registration.agent_id}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.base_url}/agents",
                    json={
                        "name": registration.name,
                        "description": registration.description,
                        "connector_type": "adk",
                        "integration_profile": {
                            "connection_model": "session_addressable",
                            "message_exchange": True,
                            "pre_invocation_mediation": [],
                            "post_invocation_mediation": [],
                            "event_reporting": ["message", "activity"],
                        },
                        "overwrite": True,
                    },
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
                res.raise_for_status()
                return res.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def post_message(self, room_ref: str, text: str, metadata: dict = None) -> dict:
        """
        Posts a message to a Switch room via the official Agent Protocol:
        POST /agents/{agent_id}/message with {room_id, content}.
        """
        if not self.is_configured:
            logger.info(f"Switch post_message (stub): [Room: {room_ref}] {text[:80]}...")
            return {"status": "pending_credentials", "room_ref": room_ref}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Primary official endpoint: /agents/{agent_id}/message
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/message",
                    json={"room_id": room_ref, "content": text, "metadata": metadata or {}},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()

                # Fallback: /agents/{agent_id}/ops/post_message
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/ops/post_message",
                    json={"room_id": room_ref, "content": text},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()

                return {"status": "error", "status_code": res.status_code, "detail": res.text}
        except Exception as e:
            logger.warning(f"Switch post_message warning: {e}")
            return {"status": "error", "error": str(e)}

    async def start_websocket_listener(self, rooms: List[str] = None):
        """
        Connects over WebSocket according to Switch Agent Protocol:
        /agents/{agent_id}/connection/ws with ping/pong and message dispatch.
        """
        if not self.is_configured or not websockets:
            logger.info("Switch WebSocket listener unavailable (missing credentials or websockets library).")
            return

        ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        conn_id = self.connection_id or f"conn-{self.agent_id}-ws"
        ws_url = f"{ws_base}/agents/{self.agent_id}/connection/ws?connection_id={conn_id}"

        async def _ws_loop():
            while not self._stop_event.is_set():
                try:
                    headers = {"Authorization": f"Bearer {self.token}"}
                    async with websockets.connect(ws_url, extra_headers=headers) as ws:
                        logger.info(f"Connected to Switch WebSocket: {ws_url}")
                        self.state = ConnectionState.CONNECTED
                        async for raw_msg in ws:
                            if self._stop_event.is_set():
                                break
                            try:
                                msg = json.loads(raw_msg)
                                msg_type = msg.get("type", "")

                                if msg_type == "ping":
                                    await ws.send(json.dumps({"type": "pong", "cursor": msg.get("cursor", 0)}))
                                    await self._emit("ping", msg)
                                elif msg_type == "message":
                                    payload = msg.get("payload", {})
                                    if payload.get("addressed") or not payload:
                                        await self._emit("message", payload)
                                else:
                                    await self._emit(msg_type, msg)
                            except json.JSONDecodeError:
                                pass
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Switch WebSocket disconnected, reconnecting in 5s: {e}")
                    await asyncio.sleep(5.0)

        self._ws_task = asyncio.create_task(_ws_loop())

    def status(self) -> dict:
        return {
            "connected": self.state == ConnectionState.CONNECTED,
            "state": self.state.value,
            "agent_id": self.agent_id,
            "connection_id": self.connection_id,
            "is_configured": self.is_configured,
        }
