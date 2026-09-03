"""
Process Supervisor and Windows Job Object Management for Desktop WebView Reviewer.
Ensures deterministic process-tree tracking, PID reuse protection via create_time validation,
and guaranteed child process teardown via JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Any

from runtime.errors import TargetExitedException, CleanupErrorException

logger = logging.getLogger("desktop_webview.process_supervisor")

try:
    import psutil
except ImportError:
    psutil = None

# Win32 Constants for Job Objects
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


# Win32 Job Object Structures
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


@dataclass
class SupervisedProcess:
    """Metadata tracking a controlled process and its Job Object."""
    pid: int
    binary_path: str
    command_line: List[str]
    creation_time: float
    job_handle: Optional[int] = None
    is_external: bool = False             # True if attached (not launched by reviewer)
    started_at: datetime = field(default_factory=datetime.utcnow)
    exit_code: Optional[int] = None

    def is_alive(self) -> bool:
        """Verifies if the process is currently running and create_time matches."""
        if psutil is not None:
            try:
                p = psutil.Process(self.pid)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    return False
                # Verify create_time within 2 seconds to avoid PID recycling confusion
                if abs(p.create_time() - self.creation_time) > 2.0:
                    return False
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        try:
            os.kill(self.pid, 0)
            return True
        except (OSError, Exception):
            return False


class Win32JobObject:
    """Encapsulates a Win32 Job Object with KILL_ON_JOB_CLOSE guarantees."""

    def __init__(self, name: Optional[str] = None):
        self.handle: Optional[int] = None
        self.name = name
        if sys.platform == "win32":
            self._create_job_object()

    def _create_job_object(self) -> None:
        kernel32 = ctypes.windll.kernel32
        h_job = kernel32.CreateJobObjectW(None, self.name)
        if not h_job:
            err = ctypes.GetLastError()
            logger.error(f"Failed to create Job Object: {err}")
            return

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION),
        )
        if not res:
            err = ctypes.GetLastError()
            logger.error(f"Failed to set Job Object limit flags: {err}")
            kernel32.CloseHandle(h_job)
            return

        self.handle = int(h_job)
        logger.debug(f"Created Job Object (handle: {self.handle}) with KILL_ON_JOB_CLOSE")

    def assign_process(self, pid: int, process_handle: Optional[int] = None) -> bool:
        """Assigns target process to the Job Object."""
        if sys.platform != "win32" or not self.handle:
            return True

        kernel32 = ctypes.windll.kernel32
        close_handle_after = False
        h_proc = process_handle

        if not h_proc:
            # Open process handle with required rights
            h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
            if not h_proc:
                err = ctypes.GetLastError()
                logger.warning(f"OpenProcess for Job Object assignment failed on PID {pid}: {err}")
                return False
            close_handle_after = True

        try:
            res = kernel32.AssignProcessToJobObject(self.handle, h_proc)
            if not res:
                err = ctypes.GetLastError()
                logger.warning(f"AssignProcessToJobObject failed for PID {pid}: {err}")
                return False
            logger.debug(f"Successfully bound PID {pid} to Job Object handle {self.handle}")
            return True
        finally:
            if close_handle_after and h_proc:
                kernel32.CloseHandle(h_proc)

    def close(self) -> None:
        """Closes the Job Object handle, triggering automatic kernel termination of all member processes."""
        if sys.platform == "win32" and self.handle:
            try:
                ctypes.windll.kernel32.CloseHandle(self.handle)
                logger.debug(f"Closed Job Object handle {self.handle}")
            except Exception as e:
                logger.error(f"Error closing Job Object handle: {e}")
            finally:
                self.handle = None


class ProcessSupervisor:
    """
    Dedicated supervisor abstraction managing process launches, PID tracking,
    process-tree correlation, Job Objects, and guaranteed orphan-free cleanup.
    """

    def __init__(self):
        self._processes: Dict[int, SupervisedProcess] = {}
        self._job_objects: List[Win32JobObject] = []

    def launch_process(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        use_job_object: bool = True,
        detached: bool = True,
    ) -> SupervisedProcess:
        """
        Launches an application process and immediately binds it to a Win32 Job Object.
        Guarantees 100% cleanup of all child processes when the Job Object closes.
        """
        creationflags = 0
        if sys.platform == "win32" and detached:
            # CREATE_NEW_PROCESS_GROUP = 0x00000200
            creationflags |= 0x00000200

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=full_env,
            creationflags=creationflags,
        )

        pid = proc.pid
        creation_time = time.time()
        binary_path = cmd[0] if cmd else ""

        if psutil is not None:
            try:
                p = psutil.Process(pid)
                creation_time = p.create_time()
                try:
                    binary_path = p.exe()
                except Exception:
                    pass
            except Exception:
                pass

        job: Optional[Win32JobObject] = None
        if sys.platform == "win32" and use_job_object:
            job = Win32JobObject(name=f"DesktopReviewer_Job_{pid}_{int(creation_time)}")
            if job.handle:
                job.assign_process(pid)
                self._job_objects.append(job)

        supervised = SupervisedProcess(
            pid=pid,
            binary_path=binary_path,
            command_line=cmd,
            creation_time=creation_time,
            job_handle=job.handle if job else None,
            is_external=False,
        )
        self._processes[pid] = supervised
        logger.info(f"Supervised process launched: PID {pid} ({binary_path})")
        return supervised

    def register_external_process(self, pid: int) -> SupervisedProcess:
        """Registers an externally running target process for monitoring without attaching destructive limits."""
        creation_time = time.time()
        binary_path = ""
        cmdline = []

        if psutil is not None:
            try:
                p = psutil.Process(pid)
                creation_time = p.create_time()
                binary_path = p.exe()
                cmdline = p.cmdline()
            except Exception as e:
                logger.warning(f"Could not inspect external PID {pid}: {e}")

        supervised = SupervisedProcess(
            pid=pid,
            binary_path=binary_path,
            command_line=cmdline,
            creation_time=creation_time,
            job_handle=None,
            is_external=True,
        )
        self._processes[pid] = supervised
        return supervised

    def get_process_tree_pids(self, root_pid: int) -> Set[int]:
        """Returns the set of all PIDs in the process subtree rooted at root_pid."""
        pids: Set[int] = {root_pid}
        if psutil is not None:
            try:
                proc = psutil.Process(root_pid)
                for child in proc.children(recursive=True):
                    pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return pids

    def terminate_process(self, pid: int, timeout: float = 3.0) -> bool:
        """
        Recursively terminates a controlled process tree using graceful SIGTERM
        followed by SIGKILL fallback. Validates create_time before killing.
        """
        supervised = self._processes.get(pid)
        expected_create_time = supervised.creation_time if supervised else None

        if psutil is None:
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
                if abs(actual_create_time - expected_create_time) > 2.0:
                    logger.warning(
                        f"PID {pid} create_time mismatch (expected {expected_create_time}, got {actual_create_time}). "
                        f"Skipping kill to protect recycled PID."
                    )
                    return False
        except psutil.NoSuchProcess:
            return True
        except Exception as e:
            logger.error(f"Error accessing PID {pid}: {e}")
            return False

        try:
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, Exception):
                    pass

            gone, alive = psutil.wait_procs(children, timeout=timeout)
            for stubborn in alive:
                try:
                    stubborn.kill()
                except Exception:
                    pass

            parent.terminate()
            parent.wait(timeout=timeout)
            logger.info(f"Process tree for PID {pid} terminated cleanly.")
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.TimeoutExpired:
            try:
                parent.kill()
                return True
            except Exception:
                return False
        except Exception as e:
            logger.error(f"Error terminating process tree for PID {pid}: {e}")
            return False

    def cleanup_all(self, kill_external: bool = False) -> None:
        """
        Cleans up all tracked processes and closes all Job Objects.
        Idempotent; safe to call multiple times.
        """
        for pid, supervised in list(self._processes.items()):
            if supervised.is_external and not kill_external:
                logger.debug(f"Skipping external process PID {pid} during cleanup.")
                continue
            try:
                self.terminate_process(pid, timeout=1.5)
            except Exception as e:
                logger.warning(f"Error terminating PID {pid}: {e}")

        # Close all Job Objects (Windows kernel kills any remaining stragglers)
        for job in self._job_objects:
            try:
                job.close()
            except Exception as e:
                logger.warning(f"Error closing Job Object: {e}")
        self._job_objects.clear()
        self._processes.clear()
        logger.info("Process supervisor cleanup complete: all Job Objects closed.")
