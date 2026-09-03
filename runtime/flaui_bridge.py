"""
Python-side Native UIA3 Bridge Worker Client.
Coordinates communication with the out-of-process .NET FlaUI / UIA3 worker
(DesktopBridge.UIA3.exe) over stdio or Named Pipe JSON-RPC 2.0.
Enforces CacheRequest bulk fetching and epoch-scoped cache invalidation.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import Rect
from runtime.errors import NativeBridgeException, TargetNotFoundException

logger = logging.getLogger("desktop_webview.flaui_bridge")

DEFAULT_SIDECAR_PATH = os.path.abspath(os.path.join("src", "DesktopBridge.UIA3", "DesktopBridge.UIA3.exe"))


@dataclass(frozen=True)
class UIAElementDTO:
    """Structured data transfer object representing a native UIA control."""
    automation_id: str
    name: str
    class_name: str
    control_type: str             # "Button", "Edit", "Pane", etc.
    bounds: Rect
    is_enabled: bool
    is_offscreen: bool
    supported_patterns: Tuple[str, ...] = field(default_factory=tuple)
    hwnd: int = 0
    depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "automation_id": self.automation_id,
            "name": self.name,
            "class_name": self.class_name,
            "control_type": self.control_type,
            "bounds": self.bounds.to_dict(),
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "supported_patterns": list(self.supported_patterns),
            "hwnd": hex(self.hwnd) if self.hwnd else "0x0",
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UIAElementDTO:
        bounds_raw = data.get("bounds", {})
        bounds = Rect.from_dict(bounds_raw) if isinstance(bounds_raw, dict) else Rect(0, 0, 0, 0)
        patterns = tuple(data.get("supported_patterns", []))
        raw_hwnd = data.get("hwnd", 0)
        try:
            hwnd_val = int(str(raw_hwnd), 0) if raw_hwnd else 0
        except ValueError:
            hwnd_val = 0
        return cls(
            automation_id=str(data.get("automation_id", "")),
            name=str(data.get("name", "")),
            class_name=str(data.get("class_name", "")),
            control_type=str(data.get("control_type", "Unknown")),
            bounds=bounds,
            is_enabled=bool(data.get("is_enabled", True)),
            is_offscreen=bool(data.get("is_offscreen", False)),
            supported_patterns=patterns,
            hwnd=hwnd_val,
            depth=int(data.get("depth", 0)),
        )


class FlaUIBridge:
    """
    Structured Python interface to the .NET FlaUI / UIA3 worker.
    Manages process lifecycle, JSON-RPC communication, CacheRequest bulk fetching,
    and epoch-scoped caching.
    """

    def __init__(
        self,
        sidecar_path: Optional[str] = None,
        use_stdio: bool = True,
        pipe_name: Optional[str] = None,
    ):
        self.sidecar_path = sidecar_path or DEFAULT_SIDECAR_PATH
        self.use_stdio = use_stdio
        self.pipe_name = pipe_name
        self._proc: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._is_connected = False
        self._cached_epoch: int = -1
        # In-memory epoch-scoped element cache: (epoch, hwnd, max_depth) -> List[UIAElementDTO]
        self._tree_cache: Dict[Tuple[int, int, int], List[UIAElementDTO]] = {}

    @property
    def is_connected(self) -> bool:
        return self._is_connected and (self._proc is not None and self._proc.poll() is None)

    async def connect(self, timeout: float = 5.0) -> bool:
        """Spawns the out-of-process worker and executes the JSON-RPC handshake."""
        async with self._lock:
            if self.is_connected:
                return True

            if not os.path.exists(self.sidecar_path):
                logger.warning(f"FlaUI sidecar binary not found at {self.sidecar_path}")
                return False

            cmd = [self.sidecar_path]
            if self.use_stdio:
                cmd.append("--stdio")
            elif self.pipe_name:
                cmd.extend(["--pipe", self.pipe_name])

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                # Send handshake
                resp = await self._send_request_locked("handshake", {})
                if resp and resp.get("status") == "READY":
                    self._is_connected = True
                    logger.debug(f"FlaUI sidecar connected: version={resp.get('sidecar_version')}")
                    return True
                else:
                    logger.error(f"FlaUI handshake failed: unexpected response {resp}")
                    self._cleanup_process()
                    return False
            except Exception as ex:
                logger.warning(f"Failed to start FlaUI sidecar: {ex}")
                self._cleanup_process()
                return False

    async def health(self) -> Dict[str, Any]:
        """Queries sidecar health status."""
        async with self._lock:
            if not self.is_connected:
                return {"status": "DISCONNECTED", "healthy": False}
            try:
                res = await self._send_request_locked("health", {})
                return {"status": res.get("status", "UNKNOWN"), "healthy": True, "details": res}
            except Exception as e:
                return {"status": "ERROR", "healthy": False, "error": str(e)}

    async def ping(self) -> bool:
        """Pings sidecar."""
        async with self._lock:
            if not self.is_connected:
                return False
            try:
                res = await self._send_request_locked("ping", {})
                return bool(res.get("pong", False))
            except Exception:
                return False

    async def get_window_root(self, hwnd: int) -> Optional[UIAElementDTO]:
        """Queries the root AutomationElement for a top-level native window."""
        async with self._lock:
            if not self.is_connected:
                return None
            try:
                data = await self._send_request_locked("get_window_root", {"hwnd": hwnd})
                if data and isinstance(data, dict) and "error" not in data:
                    return UIAElementDTO.from_dict(data)
                return None
            except Exception as e:
                logger.debug(f"get_window_root failed for HWND {hwnd}: {e}")
                return None

    async def find_children(
        self,
        hwnd: int,
        max_depth: int = 2,
        use_cache: bool = True,
        epoch: int = 1,
    ) -> List[UIAElementDTO]:
        """
        Enumerates child/descendant controls up to max_depth using native CacheRequest.
        Caches results within the active epoch to prevent redundant cross-process COM calls.
        Invalidates automatically when epoch advances.
        """
        # Epoch cache validation
        if self._cached_epoch != epoch:
            self.invalidate_cache(epoch)

        cache_key = (epoch, hwnd, max_depth)
        if cache_key in self._tree_cache:
            return self._tree_cache[cache_key]

        async with self._lock:
            if not self.is_connected:
                return []
            try:
                params = {
                    "hwnd": hwnd,
                    "max_depth": max_depth,
                    "use_cache": use_cache,
                }
                raw_list = await self._send_request_locked("find_children", params)
                results: List[UIAElementDTO] = []
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, dict):
                            results.append(UIAElementDTO.from_dict(item))

                # Cache under current epoch
                self._tree_cache[cache_key] = results
                return results
            except Exception as e:
                logger.debug(f"find_children failed for HWND {hwnd}: {e}")
                return []

    async def read_properties(self, hwnd: int, automation_id: Optional[str] = None) -> Dict[str, Any]:
        """Reads detailed properties for a control."""
        async with self._lock:
            if not self.is_connected:
                return {}
            try:
                params: Dict[str, Any] = {"hwnd": hwnd}
                if automation_id:
                    params["automation_id"] = automation_id
                return await self._send_request_locked("read_properties", params)
            except Exception as e:
                logger.debug(f"read_properties failed: {e}")
                return {}

    async def read_supported_patterns(self, hwnd: int, automation_id: Optional[str] = None) -> List[str]:
        """Reads supported control patterns for a control."""
        async with self._lock:
            if not self.is_connected:
                return []
            try:
                params: Dict[str, Any] = {"hwnd": hwnd}
                if automation_id:
                    params["automation_id"] = automation_id
                res = await self._send_request_locked("read_supported_patterns", params)
                return res if isinstance(res, list) else []
            except Exception as e:
                logger.debug(f"read_supported_patterns failed: {e}")
                return []

    def invalidate_cache(self, new_epoch: int) -> None:
        """Invalidates all cached native UIA observations upon epoch boundary or UI mutation."""
        self._tree_cache.clear()
        self._cached_epoch = new_epoch
        logger.debug(f"FlaUI element cache invalidated for new epoch {new_epoch}")

    async def disconnect(self) -> None:
        """Gracefully disconnects and shuts down the out-of-process worker."""
        async with self._lock:
            if self._proc is not None:
                try:
                    await self._send_request_locked("shutdown", {})
                except Exception:
                    pass
                self._cleanup_process()
            self._is_connected = False

    def _cleanup_process(self) -> None:
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                if self._proc.stdout:
                    self._proc.stdout.close()
                if self._proc.stderr:
                    self._proc.stderr.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._is_connected = False

    async def _send_request_locked(self, method: str, params: Dict[str, Any]) -> Any:
        """Low-level JSON-RPC request sender. Must be called under self._lock."""
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise NativeBridgeException("Sidecar process is not running or IO streams unavailable.")

        self._req_id += 1
        req_id = self._req_id
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        wire_data = json.dumps(payload) + "\n"

        loop = asyncio.get_running_loop()

        # Send request off-thread to avoid blocking event loop
        await loop.run_in_executor(None, self._write_stdin, wire_data)
        resp_line = await loop.run_in_executor(None, self._read_stdout)

        if not resp_line:
            raise NativeBridgeException("Sidecar returned EOF or empty response.")

        try:
            resp_dict = json.loads(resp_line.strip())
        except json.JSONDecodeError as ex:
            raise NativeBridgeException(f"Invalid JSON from sidecar: {ex}")

        if "error" in resp_dict:
            err = resp_dict["error"]
            raise NativeBridgeException(f"Sidecar error ({err.get('code')}): {err.get('message')}")

        return resp_dict.get("result")

    def _write_stdin(self, data: str) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def _read_stdout(self) -> str:
        if self._proc and self._proc.stdout:
            return self._proc.stdout.readline()
        return ""
