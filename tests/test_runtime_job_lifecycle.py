"""
Test Suite: Process-Tree Supervision and Job Object Lifecycle.
Verifies multi-generation process tree containment, kernel-level Job Object queries
(IsProcessInJob and QueryInformationJobObject), guaranteed teardown via KILL_ON_JOB_CLOSE,
and strict PID reuse defense via create_time validation.
"""

import os
import sys
import time
import unittest

from runtime.process_supervisor import ProcessSupervisor, Win32JobObject, SupervisedProcess
from runtime.errors import TargetMismatchException

try:
    import psutil
except ImportError:
    psutil = None


class TestRuntimeJobLifecycle(unittest.TestCase):
    """Deep verification of ProcessSupervisor and Win32JobObject kernel lifecycle."""

    def setUp(self):
        self.supervisor = ProcessSupervisor()

    def tearDown(self):
        self.supervisor.cleanup_all(kill_external=True)

    def test_job_object_assignment_and_membership(self):
        """
        Verifies root process assignment to Job Object, IsProcessInJob kernel query,
        and QueryInformationJobObject PID enumeration.
        """
        if sys.platform != "win32":
            self.skipTest("Job Objects are Windows-specific")

        # Spawn a long-lived sleep process in python
        cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
        supervised = self.supervisor.launch_process(cmd, use_job_object=True)

        self.assertIsNotNone(supervised)
        self.assertGreater(supervised.pid, 0)
        self.assertTrue(supervised.is_alive())

        job = self.supervisor.get_job_for_process(supervised.pid)
        self.assertIsNotNone(job)
        self.assertIsNotNone(job.handle)

        # 1. Kernel Query: IsProcessInJob
        in_job = job.is_process_in_job(supervised.pid)
        self.assertTrue(in_job, f"PID {supervised.pid} must be in Job Object via IsProcessInJob")

        # 2. Kernel Query: QueryInformationJobObject(JobObjectBasicProcessIdList)
        job_pids = job.get_process_ids()
        self.assertIn(supervised.pid, job_pids)

        # Clean up
        self.supervisor.terminate_process(supervised.pid)
        self.assertFalse(supervised.is_alive())

    def test_multi_generation_process_tree_teardown(self):
        """
        Spawns a 3-generation process tree (parent -> child -> grandchild).
        Verifies that Job Object termination or close tears down all generations with zero orphans.
        """
        if sys.platform != "win32":
            self.skipTest("Job Objects are Windows-specific")

        # Script that spawns a child, which spawns a grandchild
        tree_script = (
            "import subprocess, sys, time\n"
            "child_code = '''\n"
            "import subprocess, sys, time\n"
            "grandchild_code = 'import time; time.sleep(120)'\n"
            "p2 = subprocess.Popen([sys.executable, '-c', grandchild_code])\n"
            "time.sleep(120)\n"
            "'''\n"
            "p1 = subprocess.Popen([sys.executable, '-c', child_code])\n"
            "time.sleep(120)\n"
        )

        supervised = self.supervisor.launch_process(
            [sys.executable, "-c", tree_script], use_job_object=True
        )
        parent_pid = supervised.pid
        time.sleep(1.5)  # Allow child and grandchild to spawn

        # Query process tree PIDs
        tree_pids = self.supervisor.get_process_tree_pids(parent_pid)
        self.assertGreaterEqual(len(tree_pids), 2, "Must discover parent and descendant processes")

        # Verify all alive processes in the tree
        alive_pids = set()
        if psutil is not None:
            for pid in tree_pids:
                try:
                    p = psutil.Process(pid)
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        alive_pids.add(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        self.assertIn(parent_pid, alive_pids)

        # Terminate process tree via Job Object close
        job = self.supervisor.get_job_for_process(parent_pid)
        self.assertIsNotNone(job)
        job.close()  # Triggers KILL_ON_JOB_CLOSE in Windows kernel
        time.sleep(0.5)

        # Verify that parent and all descendants are 100% dead
        if psutil is not None:
            for pid in tree_pids:
                try:
                    p = psutil.Process(pid)
                    is_running = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
                    self.assertFalse(
                        is_running,
                        f"PID {pid} survived Job Object close! Orphan detected.",
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    def test_pid_reuse_protection_create_time_validation(self):
        """
        Verifies verify_pid_identity succeeds with matching create_time and
        rejects when create_time differs by > 1.0s (defending against recycled PIDs).
        """
        if psutil is None:
            self.skipTest("Requires psutil for create_time verification")

        current_pid = os.getpid()
        proc = psutil.Process(current_pid)
        actual_create_time = proc.create_time()

        # 1. Matching create_time should verify True
        self.assertTrue(
            self.supervisor.verify_pid_identity(current_pid, actual_create_time)
        )
        self.assertTrue(
            self.supervisor.verify_pid_identity(current_pid, actual_create_time + 0.5)
        )

        # 2. Mismatched create_time (> 1.0s) should verify False
        self.assertFalse(
            self.supervisor.verify_pid_identity(current_pid, actual_create_time + 2.0)
        )
        self.assertFalse(
            self.supervisor.verify_pid_identity(current_pid, actual_create_time - 100.0)
        )

    def test_termination_aborts_on_pid_reuse(self):
        """
        Verifies terminate_process detects mismatched create_time and refuses to kill
        the unrelated process.
        """
        if psutil is None:
            self.skipTest("Requires psutil")

        current_pid = os.getpid()
        proc = psutil.Process(current_pid)

        # Register current test process under a fake old create_time
        fake_time = proc.create_time() - 5000.0
        self.supervisor._processes[current_pid] = SupervisedProcess(
            pid=current_pid,
            binary_path=sys.executable,
            command_line=[],
            creation_time=fake_time,
            job_handle=None,
            is_external=False,
        )

        # Attempting termination should refuse to kill because create_time mismatches
        res = self.supervisor.terminate_process(current_pid)
        self.assertFalse(res, "Termination must be rejected when create_time mismatches")

        # Verify current process is still alive and was NOT killed!
        self.assertTrue(proc.is_running())


if __name__ == "__main__":
    unittest.main()
