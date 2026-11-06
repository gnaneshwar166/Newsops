"""
NewsOps Revision 2 - Switch Agent Protocol Client.

Implements HTTP operations, WebSocket event streaming, and connection state management
according to the official Switch Agent Protocol (https://docs.switchagents.ai/switch-rooms/internals/agent-protocol).

Provides:
- WebSocket event subscription & ping/pong liveness
- HTTP agent operations & ops discovery
- Message posting with Markdown & metadata
- Typing indicators & status updates
- Room management & participant discovery
- Resilient reconnection with backoff
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
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class AgentRegistration:
    agent_id: str
    name: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    connector_type: str = "adk"


class SwitchProtocolClient:
    """
    Official Switch Agent Protocol Client.
    Supports HTTP ops, WebSocket event streaming, typing indicators, and discovery.
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
        self.subscribed_rooms: List[str] = []
        self.supported_ops: List[str] = []

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Agent-ID": self.agent_id,
        }
        if self.connection_id:
            headers["X-Connection-ID"] = self.connection_id
        return headers

    def on(self, event_type: str, handler: Callable):
        """Register an event listener (e.g. 'message', 'ping', 'connected', 'handoff')."""
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
        """Verifies credentials against Switch server health or root endpoint."""
        if not self.is_configured:
            logger.info("SwitchProtocolClient: Credentials not configured. Operating in stub/standby mode.")
            self.state = ConnectionState.DISCONNECTED
            return False

        self.state = ConnectionState.CONNECTING
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/health", headers=self._headers())
                if res.status_code == 404:
                    res = await client.get(f"{self.base_url}/", headers=self._headers())
                res.raise_for_status()

            self.state = ConnectionState.CONNECTED
            self.connection_id = f"conn-{self.agent_id}-{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(f"Connected to Switch platform (conn: {self.connection_id})")
            await self._emit("connected", {"connection_id": self.connection_id})

            # Automatically discover supported operations
            await self.discover_operations()
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

    async def discover_operations(self) -> List[str]:
        """Discovers supported agent operations from GET /agents/{id}/ops."""
        if not self.is_configured:
            return ["post_message", "candidates", "verify", "digest", "publish"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/agents/{self.agent_id}/ops", headers=self._headers())
                if res.status_code == 200:
                    ops_data = res.json()
                    if isinstance(ops_data, dict):
                        self.supported_ops = list(ops_data.keys())
                    elif isinstance(ops_data, list):
                        self.supported_ops = [str(o) for o in ops_data]
                    return self.supported_ops
        except Exception as e:
            logger.warning(f"Failed to discover Switch operations: {e}")
        return []

    async def call_operation(self, operation: str, body: dict = None) -> dict:
        """Invokes a specific Switch operation via POST /agents/{id}/ops/{operation}."""
        if not self.is_configured:
            return {"status": "pending_credentials", "operation": operation}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/ops/{operation}",
                    json=body or {},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()
                return {"status": "error", "status_code": res.status_code, "detail": res.text}
        except Exception as e:
            return {"status": "error", "error": str(e)}

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
                        "connector_type": registration.connector_type,
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
            return {"status": "pending_credentials", "room_ref": room_ref, "preview": text[:80]}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/message",
                    json={"room_id": room_ref, "content": text, "metadata": metadata or {}},
                    headers=self._headers(),
                )
                if res.status_code in (200, 201):
                    return res.json()

                # Fallback to ops/post_message
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

    async def set_typing(self, room_ref: str, is_typing: bool = True) -> bool:
        """Sends typing activity indicator in room."""
        if not self.is_configured:
            return True
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/typing",
                    json={"room_id": room_ref, "typing": is_typing},
                    headers=self._headers(),
                )
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def update_status(self, status_text: str) -> bool:
        """Updates agent runtime status in Switch Console."""
        if not self.is_configured:
            return True
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/status",
                    json={"status": status_text},
                    headers=self._headers(),
                )
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def subscribe_room(self, room_id: str) -> bool:
        """Subscribes the connection to cover events in a room."""
        if room_id not in self.subscribed_rooms:
            self.subscribed_rooms.append(room_id)
        if not self.is_configured:
            return True
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    f"{self.base_url}/agents/{self.agent_id}/connection/subscribe",
                    json={"room_id": room_id},
                    headers=self._headers(),
                )
                return res.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Failed to subscribe room {room_id}: {e}")
            return False

    async def get_room_history(self, room_id: str, limit: int = 30) -> List[dict]:
        """Fetches recent room history from /agents/{id}/rooms/{room_id}/history."""
        if not self.is_configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(
                    f"{self.base_url}/agents/{self.agent_id}/rooms/{room_id}/history",
                    params={"limit": limit},
                    headers=self._headers(),
                )
                if res.status_code == 200:
                    data = res.json()
                    return data if isinstance(data, list) else data.get("messages", [])
        except Exception as e:
            logger.warning(f"Failed to get room history for {room_id}: {e}")
        return []

    async def start_websocket_listener(self):
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
                    self.state = ConnectionState.RECONNECTING
                    await asyncio.sleep(5.0)

        self._ws_task = asyncio.create_task(_ws_loop())

    def status(self) -> dict:
        return {
            "connected": self.state == ConnectionState.CONNECTED,
            "state": self.state.value,
            "agent_id": self.agent_id,
            "connection_id": self.connection_id,
            "is_configured": self.is_configured,
            "subscribed_rooms": self.subscribed_rooms,
            "supported_ops": self.supported_ops,
        }
