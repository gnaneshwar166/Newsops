"""
NewsOps Revision 2 - Switch Agent Protocol Integration.
"""

from .protocol import SwitchProtocolClient, ConnectionState, AgentRegistration
from .agents.scout import ScoutAgent
from .agents.analyst import AnalystSwitchAgent
from .agents.editor import EditorAgent
from .orchestrator import SwitchNewsOpsOrchestrator

__all__ = [
    "SwitchProtocolClient",
    "ConnectionState",
    "AgentRegistration",
    "ScoutAgent",
    "AnalystSwitchAgent",
    "EditorAgent",
    "SwitchNewsOpsOrchestrator",
]
