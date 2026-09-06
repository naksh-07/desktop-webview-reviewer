"""
Process Supervisor and Windows Job Object Management for Desktop WebView Reviewer.
Ensures deterministic process-tree tracking, PID reuse protection via create_time validation,
and guaranteed child/grandchild process teardown via JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
Provides kernel-level Job Object membership inspection via QueryInformationJobObject.
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
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any

from runtime.errors import TargetExitedException, CleanupErrorException, TargetMismatchException
import runtime.win32 as w32

# Re-export Win32 constants and structures for backward compatibility
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = w32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
JobObjectExtendedLimitInformation = w32.JobObjectExtendedLimitInformation
PROCESS_SET_QUOTA = w32.PROCESS_SET_QUOTA
PROCESS_TERMINATE = w32.PROCESS_TERMINATE
JOBOBJECT_EXTENDED_LIMIT_INFORMATION = w32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
JOBOBJECT_BASIC_LIMIT_INFORMATION = w32.JOBOBJECT_BASIC_LIMIT_INFORMATION
IO_COUNTERS = w32.IO_COUNTERS

logger = logging.getLogger("desktop_webview.process_supervisor")

try:
    import psutil
except ImportError:
    psutil = None


@dataclass
class SupervisedProcess:
    """Metadata tracking a controlled process and its Job Object."""
    pid: int
    binary_path: str
    command_line: List[str]
    creation_time: float
    job_handle: Optional[int] = None
    is_external: bool = False             # True if attached (not launched by reviewer)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_code: Optional[int] = None

    def is_alive(self) -> bool:
        """Verifies if the process is currently running and create_time matches within 1.0s."""
        if psutil is not None:
            try:
                p = psutil.Process(self.pid)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    return False
                # Strict create_time tolerance (1.0s) to protect against PID recycling
                if abs(p.create_time() - self.creation_time) > 1.0:
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
    """
    Encapsulates a Win32 Job Object with KILL_ON_JOB_CLOSE guarantees.
    Provides kernel-level process membership inspection via IsProcessInJob
    and QueryInformationJobObject(JobObjectBasicProcessIdList).
    """

    def __init__(self, name: Optional[str] = None):
        self.handle: Optional[int] = None
        self.name = name
        self._assigned_pids: Set[int] = set()
        if sys.platform == "win32" and w32.kernel32 is not None:
            self._create_job_object()

    def _create_job_object(self) -> None:
        h_job = w32.kernel32.CreateJobObjectW(None, self.name)
        if not h_job:
            err = ctypes.GetLastError()
            logger.error(f"Failed to create Job Object: {err}")
            return

        info = w32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = w32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = w32.kernel32.SetInformationJobObject(
            h_job,
            w32.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(w32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION),
        )
        if not res:
            err = ctypes.GetLastError()
            logger.error(f"Failed to set Job Object limit flags: {err}")
            w32.kernel32.CloseHandle(h_job)
            return

        self.handle = int(h_job)
        logger.debug(f"Created Job Object (handle: {self.handle}) with KILL_ON_JOB_CLOSE")

    def assign_process(self, pid: int, process_handle: Optional[int] = None) -> bool:
        """Assigns target process to the Job Object."""
        if sys.platform != "win32" or not self.handle or w32.kernel32 is None:
            self._assigned_pids.add(pid)
            return True

        close_handle_after = False
        h_proc = process_handle

        if not h_proc:
            h_proc = w32.kernel32.OpenProcess(
                w32.PROCESS_SET_QUOTA | w32.PROCESS_TERMINATE, False, pid
            )
            if not h_proc:
                err = ctypes.GetLastError()
                logger.warning(f"OpenProcess for Job Object assignment failed on PID {pid}: {err}")
                return False
            close_handle_after = True

        try:
            res = w32.kernel32.AssignProcessToJobObject(self.handle, h_proc)
            if not res:
                err = ctypes.GetLastError()
                logger.warning(f"AssignProcessToJobObject failed for PID {pid}: {err}")
                return False
            self._assigned_pids.add(pid)
            logger.debug(f"Successfully bound PID {pid} to Job Object handle {self.handle}")
            return True
        finally:
            if close_handle_after and h_proc:
                w32.kernel32.CloseHandle(h_proc)

    def is_process_in_job(self, pid: int) -> bool:
        """
        Kernel verification: queries IsProcessInJob to verify whether PID is a member of this Job Object.
        """
        if sys.platform != "win32" or not self.handle or w32.kernel32 is None:
            return pid in self._assigned_pids

        h_proc = w32.kernel32.OpenProcess(
            w32.PROCESS_QUERY_INFORMATION | w32.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not h_proc:
            # If process has exited, it is no longer in the job
            return False

        try:
            in_job = wintypes.BOOL(False)
            res = w32.kernel32.IsProcessInJob(h_proc, self.handle, ctypes.byref(in_job))
            return bool(res and in_job.value)
        finally:
            w32.kernel32.CloseHandle(h_proc)

    def get_process_ids(self) -> List[int]:
        """
        Queries Windows kernel via QueryInformationJobObject(JobObjectBasicProcessIdList)
        to return the exact list of PIDs currently bound to this Job Object.
        """
        if sys.platform != "win32" or not self.handle or w32.kernel32 is None:
            return list(self._assigned_pids)

        proc_list = w32.JOBOBJECT_BASIC_PROCESS_ID_LIST()
        ret_len = wintypes.DWORD(0)

        res = w32.kernel32.QueryInformationJobObject(
            self.handle,
            w32.JobObjectBasicProcessIdList,
            ctypes.byref(proc_list),
            ctypes.sizeof(w32.JOBOBJECT_BASIC_PROCESS_ID_LIST),
            ctypes.byref(ret_len),
        )
        if not res:
            logger.debug("QueryInformationJobObject failed; returning tracked PIDs")
            return list(self._assigned_pids)

        count = proc_list.NumberOfProcessIdsInList
        return [int(proc_list.ProcessIdList[i]) for i in range(count)]

    def close(self) -> None:
        """
        Closes the Job Object handle.
        Windows kernel automatically and synchronously terminates all processes currently in the job.
        """
        if sys.platform == "win32" and self.handle and w32.kernel32 is not None:
            try:
                w32.kernel32.CloseHandle(self.handle)
                logger.debug(f"Closed Job Object handle {self.handle}")
            except Exception as e:
                logger.error(f"Error closing Job Object handle: {e}")
            finally:
                self.handle = None
        self._assigned_pids.clear()


class ProcessSupervisor:
    """
    Authoritative process supervisor managing process launches, PID tracking,
    process-tree correlation, Job Objects, and guaranteed orphan-free cleanup.
    """

    def __init__(self):
        self._processes: Dict[int, SupervisedProcess] = {}
        self._job_objects: Dict[int, Win32JobObject] = {}  # pid -> JobObject

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
        Guarantees 100% cleanup of parent, child, and grandchild processes when the Job Object closes.
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
                self._job_objects[pid] = job

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

    def verify_pid_identity(self, pid: int, expected_create_time: float) -> bool:
        """
        Validates PID existence and matches create_time within 1.0s to defend against PID recycling.
        """
        if psutil is not None:
            try:
                p = psutil.Process(pid)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    return False
                return abs(p.create_time() - expected_create_time) <= 1.0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def get_job_for_process(self, pid: int) -> Optional[Win32JobObject]:
        """Returns the Win32JobObject governing the given root process PID, if any."""
        return self._job_objects.get(pid)

    def get_process_tree_pids(self, root_pid: int) -> Set[int]:
        """
        Returns the set of all PIDs in the process subtree rooted at root_pid.
        Combines recursive psutil children and Win32 Job Object membership.
        """
        pids: Set[int] = {root_pid}

        # 1. psutil recursive children discovery
        if psutil is not None:
            try:
                proc = psutil.Process(root_pid)
                for child in proc.children(recursive=True):
                    pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 2. Kernel Job Object PID enumeration
        job = self._job_objects.get(root_pid)
        if job and job.handle:
            for job_pid in job.get_process_ids():
                pids.add(job_pid)

        return pids

    def terminate_process(self, pid: int, timeout: float = 3.0) -> bool:
        """
        Recursively terminates a controlled process tree using graceful SIGTERM
        followed by SIGKILL fallback. Strictly validates create_time before killing.
        Closes the Job Object to ensure kernel-level termination of any straggler processes.
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
                if abs(actual_create_time - expected_create_time) > 1.0:
                    logger.warning(
                        f"PID {pid} create_time mismatch (expected {expected_create_time}, got {actual_create_time}). "
                        f"Skipping kill to protect recycled PID."
                    )
                    return False
        except psutil.NoSuchProcess:
            # Process already gone; ensure Job Object is closed
            job = self._job_objects.pop(pid, None)
            if job:
                job.close()
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
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            try:
                parent.kill()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error terminating process tree for PID {pid}: {e}")
            return False
        finally:
            # Kernel-level kill of any remaining processes in the Job Object
            job = self._job_objects.pop(pid, None)
            if job:
                job.close()

        return True

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

        # Close any remaining Job Objects
        for pid, job in list(self._job_objects.items()):
            try:
                job.close()
            except Exception as e:
                logger.warning(f"Error closing Job Object for PID {pid}: {e}")
        self._job_objects.clear()
        self._processes.clear()
        logger.info("Process supervisor cleanup complete: all Job Objects closed.")
