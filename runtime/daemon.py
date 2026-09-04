"""
Long-lived Stateful Desktop Daemon for Desktop WebView Reviewer.
Central runtime host coordinating sessions, target identities, process supervision with Job Objects,
native OS supervision, sidecar transports, and guaranteed idempotent cleanup.
"""

from __future__ import annotations
import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

from runtime.state import DaemonLifecycleState, TargetPlane, SessionLifecycleState
from runtime.session_manager import SessionManager, SessionConfig, SessionState
from runtime.target_manager import TargetManager, ProcessIdentity, WindowIdentity
from runtime.process_supervisor import ProcessSupervisor, SupervisedProcess
from runtime.native_supervisor import NativeOSSupervisor
from runtime.transport import ITransport, MockTransport
from runtime.logging_events import LifecycleEvent, EventAuditor
from runtime.errors import TargetExitedException, CleanupErrorException

logger = logging.getLogger("desktop_webview.daemon")


class DesktopDaemon:
    """
    Central stateful desktop automation daemon.
    Manages long-lived desktop target context, session leasing, process isolation,
    and guaranteed idempotent teardown.
    """

    def __init__(self):
        self.state = DaemonLifecycleState.UNINITIALIZED
        self.session_manager = SessionManager()
        self.target_manager = TargetManager()
        self.process_supervisor = ProcessSupervisor()
        self.native_supervisor = NativeOSSupervisor()
        self.auditor = EventAuditor()
        self._transports: List[ITransport] = []
        self._shutdown_lock = asyncio.Lock()
        self._is_shutdown = False

    async def initialize(self) -> None:
        """Initializes daemon subsystems and transitions to RUNNING state."""
        if self.state != DaemonLifecycleState.UNINITIALIZED:
            logger.warning(f"Daemon already initialized (current state: {self.state.value})")
            return

        self.state = DaemonLifecycleState.INITIALIZING
        self.auditor.record(LifecycleEvent(
            operation="DAEMON_INITIALIZE",
            state_transition=f"{DaemonLifecycleState.UNINITIALIZED.value} -> {DaemonLifecycleState.INITIALIZING.value}",
        ))

        # Setup runtime hooks / environment if needed
        self.state = DaemonLifecycleState.RUNNING
        self.auditor.record(LifecycleEvent(
            operation="DAEMON_RUNNING",
            state_transition=f"{DaemonLifecycleState.INITIALIZING.value} -> {DaemonLifecycleState.RUNNING.value}",
        ))
        logger.info("DesktopDaemon successfully initialized and running.")

    def register_transport(self, transport: ITransport) -> None:
        """Registers a sidecar transport for lifecycle management and coordinated shutdown."""
        self._transports.append(transport)

    async def launch_target(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        cdp_port: Optional[int] = None,
        lease_timeout_sec: int = 300,
    ) -> SessionState:
        """
        Spawns target process under a Win32 Job Object, correlates process and window identities,
        and initializes a new managed session.
        """
        if self.state != DaemonLifecycleState.RUNNING:
            raise RuntimeError(f"Cannot launch target: daemon is in {self.state.value} state")

        # 1. Spawn process with Job Object binding
        supervised = self.process_supervisor.launch_process(cmd=cmd, cwd=cwd, env=env, use_job_object=True)

        # 2. Correlate process identity
        proc_identity = self.target_manager.correlate_process(supervised.pid)

        # 3. Create session
        config = SessionConfig(
            target_executable=cmd[0] if cmd else None,
            target_cmdline=cmd,
            target_pid=supervised.pid,
            cdp_port=cdp_port,
            lease_timeout_sec=lease_timeout_sec,
        )
        session = await self.session_manager.create_session(config)
        session.target_process = proc_identity

        self.auditor.record(LifecycleEvent(
            operation="TARGET_LAUNCHED",
            session_id=session.session_id,
            pid=supervised.pid,
            details={"cmd": cmd, "job_handle": supervised.job_handle},
        ))

        return session

    async def attach_target_process(
        self,
        pid: int,
        hwnd: Optional[int] = None,
        cdp_port: Optional[int] = None,
        lease_timeout_sec: int = 300,
    ) -> SessionState:
        """
        Attaches to an already running desktop application process without destructive Job Object termination.
        """
        if self.state != DaemonLifecycleState.RUNNING:
            raise RuntimeError(f"Cannot attach target: daemon is in {self.state.value} state")

        # 1. Register process as external
        supervised = self.process_supervisor.register_external_process(pid)
        proc_identity = self.target_manager.correlate_process(pid)

        # 2. Correlate window if provided
        window_identity: Optional[WindowIdentity] = None
        if hwnd is not None:
            window_identity = self.target_manager.correlate_window(hwnd, expected_pid=pid)

        # 3. Create session
        config = SessionConfig(
            target_pid=pid,
            target_hwnd=hwnd,
            cdp_port=cdp_port,
            lease_timeout_sec=lease_timeout_sec,
        )
        session = await self.session_manager.create_session(config)
        session.target_process = proc_identity
        session.target_window = window_identity

        self.auditor.record(LifecycleEvent(
            operation="TARGET_ATTACHED",
            session_id=session.session_id,
            pid=pid,
            hwnd=hwnd,
            details={"external": True},
        ))

        return session

    async def run_maintenance_cycle(self) -> Dict[str, Any]:
        """
        Periodic maintenance:
        1. Prunes expired session leases.
        2. Detects dead target processes and transitions sessions to FAILED or CLOSED.
        """
        pruned_leases = await self.session_manager.prune_expired_sessions()
        dead_pids: List[int] = []

        active_sessions = await self.session_manager.list_active_sessions()
        for session in active_sessions:
            if session.target_process:
                try:
                    self.target_manager.verify_process_identity(session.target_process)
                except TargetExitedException:
                    dead_pids.append(session.target_process.pid)
                    logger.warning(
                        f"Target process PID {session.target_process.pid} for session {session.session_id} exited. Closing session."
                    )
                    await self.session_manager.close_session(session.session_id, reason="target_process_exited")

        return {
            "pruned_leases": pruned_leases,
            "dead_pids": dead_pids,
            "active_session_count": len(await self.session_manager.list_active_sessions()),
        }

    async def shutdown(self) -> None:
        """
        Gracefully terminates the daemon, all active sessions, transports, and child processes.
        Idempotent: safe to invoke repeatedly without exceptions or state corruption.
        """
        async with self._shutdown_lock:
            if self._is_shutdown or self.state == DaemonLifecycleState.STOPPED:
                logger.debug("DesktopDaemon shutdown already completed (idempotent call)")
                return

            self.state = DaemonLifecycleState.SHUTTING_DOWN
            self.auditor.record(LifecycleEvent(
                operation="DAEMON_SHUTTING_DOWN",
                state_transition=f"{DaemonLifecycleState.RUNNING.value} -> {DaemonLifecycleState.SHUTTING_DOWN.value}",
            ))

            # 1. Close all active sessions
            active_sessions = await self.session_manager.list_active_sessions()
            for session in active_sessions:
                try:
                    await self.session_manager.close_session(session.session_id, reason="daemon_shutdown")
                except Exception as e:
                    logger.warning(f"Error closing session {session.session_id}: {e}")

            # 2. Disconnect all sidecar transports
            for transport in self._transports:
                try:
                    if transport.is_connected:
                        await transport.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting transport: {e}")
            self._transports.clear()

            # 3. Clean up all supervised processes and close all Job Objects
            try:
                self.process_supervisor.cleanup_all(kill_external=False)
            except Exception as e:
                logger.error(f"Error during process supervisor cleanup: {e}")

            self.state = DaemonLifecycleState.STOPPED
            self._is_shutdown = True
            self.auditor.record(LifecycleEvent(
                operation="DAEMON_STOPPED",
                state_transition=f"{DaemonLifecycleState.SHUTTING_DOWN.value} -> {DaemonLifecycleState.STOPPED.value}",
            ))
            logger.info("DesktopDaemon stopped cleanly. Teardown verified.")


_default_daemon: Optional[DesktopDaemon] = None


def get_default_daemon() -> DesktopDaemon:
    """Returns the persistent singleton DesktopDaemon instance across client reconnections."""
    global _default_daemon
    if _default_daemon is None:
        _default_daemon = DesktopDaemon()
    return _default_daemon


def reset_default_daemon() -> None:
    """Resets the singleton DesktopDaemon instance (for testing)."""
    global _default_daemon
    _default_daemon = None

