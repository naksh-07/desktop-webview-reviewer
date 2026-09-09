"""
Agent-Controlled Real Application Runtime.
Implements first-class AgentControlledRuntimeSession and AgentControlStatusIndicator
to provide DevTools-style desktop-reviewer-native transparency and prevent
hidden or duplicate target deception.
"""

from __future__ import annotations
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("desktop_webview.agent_control")

try:
    import psutil
except ImportError:
    psutil = None


class AgentControlState(str, Enum):
    """Lifecycle states for agent-controlled runtime session."""
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class AgentControlStatusIndicator:
    """
    Observable transparency indicator/overlay representing agent control over the target window/process.
    Binds directly to target HWND and PID. Automatically transitions to TERMINATED if the target
    process dies, PID is recycled, or the window is destroyed.
    """

    def __init__(
        self,
        session_id: str,
        target_hwnd: int,
        target_pid: int,
        process_creation_time: float = 0.0,
        indicator_text: str = "Agent is controlling this application",
    ):
        self.session_id = session_id
        self.target_hwnd = target_hwnd
        self.target_pid = target_pid
        self.process_creation_time = process_creation_time
        self.indicator_text = indicator_text
        self.control_state = AgentControlState.INACTIVE
        self.is_active = False
        self.overlay_visible = False
        self.started_at: Optional[float] = None
        self.updated_at: Optional[float] = None
        self.termination_reason: Optional[str] = None

    def activate(self, indicator_text: Optional[str] = None) -> bool:
        """Activates agent control status and overlay."""
        if not self.verify_target_liveness():
            logger.warning(
                f"Cannot activate agent control: target PID {self.target_pid} or HWND {hex(self.target_hwnd)} is invalid/dead."
            )
            return False

        if indicator_text:
            self.indicator_text = indicator_text
        now = time.time()
        self.control_state = AgentControlState.ACTIVE
        self.is_active = True
        self.overlay_visible = True
        self.started_at = self.started_at or now
        self.updated_at = now
        logger.info(
            f"Agent control activated for session {self.session_id} on PID {self.target_pid}, HWND {hex(self.target_hwnd)}"
        )
        return True

    def pause(self, reason: str = "agent_paused") -> bool:
        """Pauses agent control without terminating the session."""
        if self.control_state == AgentControlState.TERMINATED:
            return False
        self.control_state = AgentControlState.PAUSED
        self.is_active = False
        self.overlay_visible = False
        self.updated_at = time.time()
        logger.info(f"Agent control paused for session {self.session_id}: {reason}")
        return True

    def resume(self) -> bool:
        """Resumes active agent control."""
        if self.control_state == AgentControlState.TERMINATED:
            logger.warning("Cannot resume terminated agent control")
            return False
        if not self.verify_target_liveness():
            return False
        self.control_state = AgentControlState.ACTIVE
        self.is_active = True
        self.overlay_visible = True
        self.updated_at = time.time()
        logger.info(f"Agent control resumed for session {self.session_id}")
        return True

    def terminate(self, reason: str = "agent_terminated") -> bool:
        """Terminates agent control permanently."""
        self.control_state = AgentControlState.TERMINATED
        self.is_active = False
        self.overlay_visible = False
        self.termination_reason = reason
        self.updated_at = time.time()
        logger.info(f"Agent control terminated for session {self.session_id}: {reason}")
        return True

    def verify_target_liveness(self) -> bool:
        """
        Independently verifies:
        1. Target PID still exists and is alive
        2. Creation time matches (defends against PID recycling)
        3. Target HWND is still a valid OS window (if HWND > 0)
        If invalid, auto-terminates agent control.
        """
        if self.control_state == AgentControlState.TERMINATED:
            return False

        # 1. Process identity & PID recycling check
        if self.target_pid > 0 and psutil:
            try:
                if not psutil.pid_exists(self.target_pid):
                    self.terminate("target_process_exited")
                    return False
                proc = psutil.Process(self.target_pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    self.terminate("target_process_zombie_or_dead")
                    return False
                if self.process_creation_time > 0.0:
                    current_create_time = proc.create_time()
                    if abs(current_create_time - self.process_creation_time) > 0.05:
                        self.terminate("target_pid_recycled")
                        return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self.terminate("target_process_inaccessible_or_exited")
                return False

        # 2. Window liveness check (Windows platform)
        if self.target_hwnd > 0 and sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                if not user32.IsWindow(self.target_hwnd):
                    self.terminate("target_window_destroyed")
                    return False
            except Exception:
                pass

        return True

    def get_status(self) -> Dict[str, Any]:
        """Returns observable runtime status."""
        self.verify_target_liveness()
        return {
            "indicator_text": self.indicator_text,
            "is_active": self.is_active,
            "control_state": self.control_state.value,
            "overlay_visible": self.overlay_visible,
            "target_hwnd": self.target_hwnd,
            "target_pid": self.target_pid,
            "process_creation_time": self.process_creation_time,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "termination_reason": self.termination_reason,
        }


@dataclass
class AgentControlledRuntimeSession:
    """
    First-class representation of an agent-controlled desktop runtime session.
    Guarantees that actions, observations, and physical desktop captures are strictly
    bound to the supervised target process and window.
    """
    session_id: str
    target_hwnd: int
    target_pid: int
    process_creation_time: float
    agent_controlled: bool = True
    control_state: AgentControlState = AgentControlState.ACTIVE
    indicator: AgentControlStatusIndicator = field(init=False)
    current_epoch: int = 1
    started_at: float = field(default_factory=time.time)
    last_heartbeat_time: float = field(default_factory=time.time)
    controller_identity: str = "desktop-webview-reviewer"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.indicator = AgentControlStatusIndicator(
            session_id=self.session_id,
            target_hwnd=self.target_hwnd,
            target_pid=self.target_pid,
            process_creation_time=self.process_creation_time,
        )
        if self.agent_controlled and self.control_state == AgentControlState.ACTIVE:
            self.indicator.activate()

    @property
    def is_active(self) -> bool:
        return self.control_state == AgentControlState.ACTIVE and self.indicator.is_active

    def start_control(self) -> bool:
        """Starts or restarts active agent control."""
        self.control_state = AgentControlState.ACTIVE
        self.agent_controlled = True
        return self.indicator.activate()

    def pause_control(self, reason: str = "paused") -> bool:
        """Pauses agent control."""
        self.control_state = AgentControlState.PAUSED
        return self.indicator.pause(reason)

    def resume_control(self) -> bool:
        """Resumes agent control."""
        self.control_state = AgentControlState.ACTIVE
        return self.indicator.resume()

    def terminate_control(self, reason: str = "terminated") -> bool:
        """Terminates agent control."""
        self.control_state = AgentControlState.TERMINATED
        self.agent_controlled = False
        return self.indicator.terminate(reason)

    def increment_epoch(self) -> int:
        """Increments epoch counter for atomic action sequencing."""
        self.current_epoch += 1
        return self.current_epoch

    def heartbeat(self) -> None:
        """Extends agent control heartbeat."""
        self.last_heartbeat_time = time.time()
        self.indicator.verify_target_liveness()

    def verify_liveness(self) -> bool:
        """Verifies process and window liveness; auto-terminates if dead."""
        is_live = self.indicator.verify_target_liveness()
        if not is_live:
            self.control_state = AgentControlState.TERMINATED
            self.agent_controlled = False
        return is_live

    def to_dict(self) -> Dict[str, Any]:
        """Returns serializable dictionary representation."""
        return {
            "session_id": self.session_id,
            "target_hwnd": self.target_hwnd,
            "target_pid": self.target_pid,
            "process_creation_time": self.process_creation_time,
            "agent_controlled": self.agent_controlled,
            "control_state": self.control_state.value,
            "indicator": self.indicator.get_status(),
            "current_epoch": self.current_epoch,
            "started_at": self.started_at,
            "last_heartbeat_time": self.last_heartbeat_time,
            "controller_identity": self.controller_identity,
            "metadata": self.metadata,
        }
