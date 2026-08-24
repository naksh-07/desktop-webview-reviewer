"""
Detached process launcher for desktop applications.
"""

import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

from adapters.base import BaseEngineAdapter
from adapters import get_default_adapter


class ProcessLauncher:
    """Handles spawning background desktop application processes with remote debugging."""

    @staticmethod
    def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        """Checks if a TCP port is currently open / listening on host."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.4)
                s.connect((host, port))
                return True
            except (socket.timeout, ConnectionRefusedError, OSError):
                return False

    @classmethod
    def find_free_port(cls, start_port: int = 9222, max_attempts: int = 50, host: str = "127.0.0.1") -> int:
        """Finds the first available free TCP port on host starting from start_port."""
        import socket
        for p in range(start_port, start_port + max_attempts):
            if not cls.is_port_in_use(p, host=host):
                return p
        # Ephemeral OS port fallback
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return s.getsockname()[1]

    @classmethod
    def launch(
        cls,
        executable_or_script: str,
        args: Optional[List[str]] = None,
        adapter: Optional[BaseEngineAdapter] = None,
        port: int = 9222,
        pid_file: str = "desktop_app.pid",
        log_file: str = "desktop_app.log",
        init_delay: float = 2.0,
        cwd: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None
    ) -> int:
        """
        Launches the target application with debugging environment injected.
        Returns the PID of the spawned process.
        """
        extra_args = args or []
        engine_adapter = adapter or get_default_adapter()

        # Prepare environment
        base_env = os.environ.copy()
        env = engine_adapter.prepare_environment(base_env, port=port)
        if env_overrides:
            env.update(env_overrides)

        # Combine CLI flags from adapter
        launch_flags = engine_adapter.get_launch_args(port=port)
        combined_args = list(extra_args)
        for flag in launch_flags:
            flag_key = flag.split("=")[0]
            if not any(a.startswith(flag_key) for a in combined_args):
                combined_args.append(flag)

        # Build command
        if executable_or_script.endswith(".py"):
            cmd = [sys.executable, executable_or_script] + combined_args
        else:
            cmd = [executable_or_script] + combined_args

        # Resolve working directory if not explicit
        target_cwd = cwd
        if target_cwd is None and os.path.isfile(executable_or_script):
            target_cwd = os.path.dirname(os.path.abspath(executable_or_script))

        # Windows process creation flags: CREATE_NEW_PROCESS_GROUP
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        log_fp = open(log_file, "w", encoding="utf-8", errors="replace")

        process = subprocess.Popen(
            cmd,
            env=env,
            cwd=target_cwd,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags
        )
        try:
            log_fp.close()
        except Exception:
            pass

        pid = process.pid
        create_time = None
        try:
            import psutil
            proc = psutil.Process(pid)
            create_time = proc.create_time()
        except Exception:
            create_time = time.time()

        # Persist PID file (backward compatible string)
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
        except Exception:
            pass

        # Persist structured ownership metadata
        try:
            ownership_file = "desktop_ownership.json"
            ownership_data = {
                "pid": pid,
                "create_time": create_time,
                "launched_by_reviewer": True,
                "command": cmd,
                "port": port
            }
            import json
            with open(ownership_file, "w", encoding="utf-8") as f:
                json.dump(ownership_data, f, indent=2)
        except Exception:
            pass

        if init_delay > 0:
            time.sleep(init_delay)

        return pid
