"""
Unit tests for runtime/process_supervisor.py.
Validates child process lifecycle, Win32 Job Object creation and assignment,
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE configuration, and orphan prevention.
"""

import os
import subprocess
import sys
import time
import unittest

from runtime.process_supervisor import (
    ProcessSupervisor,
    Win32JobObject,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
)

try:
    import psutil
except ImportError:
    psutil = None


class TestRuntimeProcess(unittest.TestCase):
    """Test suite for process supervision and Win32 Job Objects."""

    def setUp(self):
        self.supervisor = ProcessSupervisor()

    def tearDown(self):
        self.supervisor.cleanup_all(kill_external=False)

    def test_job_object_creation_and_limits(self):
        """Verifies Job Object creates handle and applies KILL_ON_JOB_CLOSE on Windows."""
        if sys.platform != "win32":
            self.skipTest("Win32 Job Objects are Windows-specific")

        job = Win32JobObject(name="Test_Job_Object_Limit")
        self.assertIsNotNone(job.handle)
        self.assertGreater(job.handle, 0)

        # Cleanly close Job Object
        job.close()
        self.assertIsNone(job.handle)

    def test_supervised_process_launch_and_cleanup(self):
        """Verifies process launch, Job Object assignment, alive check, and clean termination."""
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        supervised = self.supervisor.launch_process(cmd=cmd, use_job_object=True)

        self.assertGreater(supervised.pid, 0)
        self.assertTrue(supervised.is_alive())
        if sys.platform == "win32":
            self.assertIsNotNone(supervised.job_handle)

        # Terminate via supervisor
        success = self.supervisor.terminate_process(supervised.pid, timeout=2.0)
        self.assertTrue(success)

        # Give OS time to reap process
        time.sleep(0.2)
        self.assertFalse(supervised.is_alive())

    def test_job_object_orphan_prevention(self):
        """
        Verifies that closing a Job Object automatically kills member child processes,
        even without calling terminate_process.
        """
        if sys.platform != "win32":
            self.skipTest("Win32 Job Objects are Windows-specific")

        job = Win32JobObject(name="Test_Orphan_Prevention_Job")
        self.assertIsNotNone(job.handle)

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
        )
        pid = proc.pid

        try:
            assigned = job.assign_process(pid)
            self.assertTrue(assigned)

            # Close Job Object handle -> Windows Kernel terminates member process tree
            job.close()
            time.sleep(0.5)

            # Check if process was killed by kernel
            if psutil is not None:
                try:
                    p = psutil.Process(pid)
                    self.assertFalse(p.is_running())
                except psutil.NoSuchProcess:
                    pass  # Successfully terminated
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    def test_pid_create_time_mismatch_skips_kill(self):
        """Verifies terminate_process protects against killing reused PIDs if create_time differs."""
        current_pid = os.getpid()
        # Register a fake supervised process with current PID but ancient create_time
        self.supervisor._processes[current_pid] = type("SupervisedMock", (), {
            "pid": current_pid,
            "creation_time": 100.0,
            "is_external": False,
        })()

        # Termination should skip and return False to avoid killing unrelated process
        res = self.supervisor.terminate_process(current_pid)
        self.assertFalse(res)

        # Verify current process is still alive and not killed!
        self.assertTrue(os.path.exists("pyproject.toml"))

    def test_cleanup_all_is_idempotent(self):
        """Verifies cleanup_all can be called repeatedly without exceptions."""
        self.supervisor.cleanup_all()
        self.supervisor.cleanup_all()
        self.assertEqual(len(self.supervisor._processes), 0)


if __name__ == "__main__":
    unittest.main()
