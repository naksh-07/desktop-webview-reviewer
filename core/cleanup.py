"""
Process lifecycle cleanup and resource teardown.
"""

import logging
import os
import sys
import time
from typing import List, Optional

logger = logging.getLogger("desktop_webview.cleanup")

try:
    import psutil
except ImportError:
    psutil = None


class ProcessCleanup:
    """Manages cross-platform process tree termination and ephemeral file cleanup."""

    @staticmethod
    def is_process_alive(pid: int) -> bool:
        """Checks if a process with the given PID is currently running."""
        if psutil is not None:
            try:
                p = psutil.Process(pid)
                return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, Exception):
            return False

    @staticmethod
    def terminate_process_tree(
        pid: int,
        timeout: float = 3.0,
        expected_create_time: Optional[float] = None
    ) -> bool:
        """
        Recursively terminates a parent process and all its spawned children (e.g. renderer processes).
        Verifies expected create_time when provided to avoid accidental termination of reused PIDs.
        Uses staged SIGTERM -> SIGKILL fallback.
        """
        if psutil is None:
            logger.warning("psutil not installed; falling back to basic process termination.")
            try:
                os.kill(pid, 9)
                return True
            except Exception as e:
                logger.error(f"Failed to kill PID {pid}: {e}")
                return False

        try:
            parent = psutil.Process(pid)
            if expected_create_time is not None:
                actual_create_time = parent.create_time()
                if abs(actual_create_time - expected_create_time) > 5.0:
                    logger.warning(
                        f"PID {pid} create_time mismatch (expected {expected_create_time}, got {actual_create_time}). "
                        f"Skipping termination to avoid killing unrelated process."
                    )
                    return False
        except psutil.NoSuchProcess:
            logger.info(f"Process {pid} no longer exists.")
            return True
        except Exception as e:
            logger.error(f"Error accessing PID {pid}: {e}")
            return False

        try:
            children = parent.children(recursive=True)
            for child in children:
                try:
                    logger.debug(f"Terminating child process PID {child.pid} ({child.name()})...")
                    child.terminate()
                except (psutil.NoSuchProcess, Exception):
                    pass

            gone, alive = psutil.wait_procs(children, timeout=timeout)
            for stubborn in alive:
                try:
                    logger.warning(f"Force killing stubborn child PID {stubborn.pid}...")
                    stubborn.kill()
                except Exception:
                    pass

            logger.debug(f"Terminating parent process PID {pid} ({parent.name()})...")
            parent.terminate()
            parent.wait(timeout=timeout)
            logger.info(f"Process tree for PID {pid} cleanly terminated.")
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.TimeoutExpired:
            try:
                parent.kill()
                logger.warning(f"Force killed parent PID {pid} after timeout.")
                return True
            except Exception as e:
                logger.error(f"Failed to force kill PID {pid}: {e}")
                return False
        except Exception as e:
            logger.error(f"Error terminating process tree for PID {pid}: {e}")
            return False

    @classmethod
    def safe_cleanup(
        cls,
        pid_file: str = "desktop_app.pid",
        ownership_file: str = "desktop_ownership.json",
        timeout: float = 3.0
    ) -> bool:
        """
        Cleans up processes safely checking ownership metadata.
        If the process was NOT launched by the reviewer (attach mode), skips termination.
        """
        import json
        pid: Optional[int] = None
        create_time: Optional[float] = None
        launched_by_reviewer = True

        if os.path.exists(ownership_file):
            try:
                with open(ownership_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    pid = data.get("pid")
                    create_time = data.get("create_time")
                    launched_by_reviewer = data.get("launched_by_reviewer", True)
            except Exception as e:
                logger.warning(f"Could not read {ownership_file}: {e}")

        if pid is None and os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
            except Exception:
                pass

        success = True
        if pid is not None:
            if launched_by_reviewer:
                logger.info(f"Terminating reviewer-launched process tree PID {pid}...")
                success = cls.terminate_process_tree(pid, timeout=timeout, expected_create_time=create_time)
            else:
                logger.info(f"Process PID {pid} was attached (not launched by reviewer). Leaving process running.")

        cls.clean_state_files([pid_file, ownership_file, "desktop_ws_url.txt", "qt_app.pid", "qt_ws_url.txt"])
        return success

    @staticmethod
    def clean_state_files(file_paths: Optional[List[str]] = None) -> None:
        """Removes temporary PID, ownership, and URL state files."""
        targets = file_paths or [
            "desktop_app.pid",
            "desktop_ownership.json",
            "desktop_ws_url.txt",
            "qt_app.pid",
            "qt_ws_url.txt"
        ]
        for path in targets:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.debug(f"Removed state file: {path}")
                except Exception as e:
                    logger.warning(f"Could not remove state file {path}: {e}")

