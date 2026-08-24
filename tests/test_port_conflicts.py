import sys
import os
import time
import socket
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

try:
    from .env_config import get_qt_skill_dir, get_python_exe
except ImportError:
    from env_config import get_qt_skill_dir, get_python_exe
SKILL_DIR = str(get_qt_skill_dir())
PYTHON_EXE = get_python_exe()


class MockHTTPHandler(BaseHTTPRequestHandler):
    mode = "invalid_json"

    def do_GET(self):
        if self.mode == "invalid_json":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"NOT_A_VALID_JSON_RESPONSE")
        elif self.mode == "non_page_target":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = [{"type": "background_page", "title": "Mock Ext", "url": "chrome-extension://xyz"}]
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.mode == "missing_ws_url":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = [{"type": "page", "title": "Page without WS URL", "url": "about:blank"}]
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.mode == "empty_list":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")
        elif self.mode == "http_500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")
        elif self.mode == "http_404":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging

def start_mock_server(port, mode):
    MockHTTPHandler.mode = mode
    server = HTTPServer(("127.0.0.1", port), MockHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def start_raw_garbage_tcp_server(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(5)
    stop_event = threading.Event()

    def handler():
        sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                conn, _ = sock.accept()
                conn.sendall(b"\x00\xff\xfeGARBAGE_BINARY_DATA\r\n")
                conn.close()
            except socket.timeout:
                continue
            except Exception:
                break
        sock.close()

    thread = threading.Thread(target=handler, daemon=True)
    thread.start()
    return stop_event, sock

def run_script_with_timeout(script_args, timeout=10, cwd=None):
    cmd = [PYTHON_EXE] + script_args
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd or os.getcwd()
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return -999, stdout, stderr + "\n[TEST HARNESS TIMEOUT]"

def test_timeout_no_port():
    print("\n=======================================================")
    print("--- Test 1.1: Discovery Timeout on Unbound Port 9222 ---")
    discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
    
    code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=3)
"""
    ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=8)
    print(f"Return code: {ret}")
    print(f"Stdout:\n{stdout.strip()}")
    assert ret == 1, f"Expected returncode 1 on timeout, got {ret}"
    assert "Timed out waiting for QtWebEngine debugging endpoint" in stdout, "Expected timeout error message"
    print(">>> RESULT: PASS (Unbound port triggers clean timeout exit code 1 without unhandled stacktrace).")

def test_occupied_port_invalid_json():
    print("\n=======================================================")
    print("--- Test 1.2: Port 9222 Occupied - Malformed Non-JSON Response ---")
    server = start_mock_server(9222, "invalid_json")
    time.sleep(0.3)
    try:
        discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
        code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=3)
"""
        ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=8)
        print(f"Return code: {ret}")
        print(f"Stdout:\n{stdout.strip()}")
        assert ret == 1, f"Expected returncode 1 on timeout, got {ret}"
        assert ("Error checking targets:" in stdout or "Timed out" in stdout)
        print(">>> RESULT: PASS (Malformed JSON handled gracefully by generic exception handler and retries to timeout).")
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.3)

def test_occupied_port_empty_list():
    print("\n=======================================================")
    print("--- Test 1.3: Port 9222 Occupied - Empty Target List '[]' ---")
    server = start_mock_server(9222, "empty_list")
    time.sleep(0.3)
    try:
        discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
        code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=3)
"""
        ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=8)
        print(f"Return code: {ret}")
        print(f"Stdout:\n{stdout.strip()}")
        assert ret == 1, f"Expected returncode 1 on timeout, got {ret}"
        assert "Endpoint responded, but no targets are available yet" in stdout
        print(">>> RESULT: PASS (Empty list detected with explicit informative log message and cleanly timed out).")
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.3)

def test_occupied_port_non_page_targets():
    print("\n=======================================================")
    print("--- Test 1.4: Port 9222 Occupied - Non-Page Targets / Missing WS URL ---")
    server = start_mock_server(9222, "non_page_target")
    time.sleep(0.3)
    try:
        discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
        code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=3)
"""
        ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=8)
        print(f"Return code: {ret}")
        print(f"Stdout:\n{stdout.strip()}")
        assert ret == 1, f"Expected returncode 1 on timeout, got {ret}"
        assert "No 'page' target with a WebSocket URL found yet" in stdout
        print(">>> RESULT: PASS (Non-page targets correctly filtered out; retries cleanly).")
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.3)

def test_occupied_port_http_errors():
    print("\n=======================================================")
    print("--- Test 1.5: Port 9222 Occupied - HTTP 404 / 500 Status ---")
    for status_mode in ["http_404", "http_500"]:
        server = start_mock_server(9222, status_mode)
        time.sleep(0.3)
        try:
            discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
            code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=2)
"""
            ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=6)
            print(f"[{status_mode}] Return code: {ret}")
            assert ret == 1, f"Expected returncode 1 on timeout for {status_mode}, got {ret}"
            print(f"[{status_mode}] >>> PASS: HTTP status error handled silently via URLError catch.")
        finally:
            server.shutdown()
            server.server_close()
            time.sleep(0.3)

def test_occupied_port_raw_garbage_tcp():
    print("\n=======================================================")
    print("--- Test 1.6: Port 9222 Occupied - Raw Binary Garbage TCP Server ---")
    stop_event, sock = start_raw_garbage_tcp_server(9222)
    time.sleep(0.3)
    try:
        discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
        code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=2)
"""
        ret, stdout, stderr = run_script_with_timeout(["-c", code], timeout=6)
        print(f"Return code: {ret}")
        print(f"Stdout:\n{stdout.strip()}")
        assert ret == 1, f"Expected returncode 1 on timeout, got {ret}"
        print(">>> RESULT: PASS (Garbage TCP packets caught and handled cleanly).")
    finally:
        stop_event.set()
        time.sleep(0.3)

def test_launch_with_occupied_port():
    print("\n=======================================================")
    print("--- Test 1.7: Full App Launch Lifecycle under Port Conflict ---")
    # Occupy port 9222 with mock HTTP server
    server = start_mock_server(9222, "empty_list")
    time.sleep(0.3)
    
    launch_script = os.path.join(SKILL_DIR, "scripts", "launch-app.py")
    test_app = os.path.join(SKILL_DIR, "examples", "test_app.py")
    stop_script = os.path.join(SKILL_DIR, "scripts", "stop-app.py")
    
    try:
        # 1. Launch Qt app while 9222 is occupied
        ret, stdout, stderr = run_script_with_timeout([launch_script, test_app], timeout=8)
        print(f"Launch return code: {ret}")
        print(f"Launch stdout:\n{stdout.strip()}")
        assert ret == 0, "launch-app.py should successfully spawn process even if port 9222 is taken"
        
        # 2. Verify PID recorded
        assert os.path.exists("qt_app.pid"), "qt_app.pid should exist"
        with open("qt_app.pid", "r") as f:
            pid = int(f.read().strip())
        print(f"Spawned Qt App PID: {pid}")
        
        # 3. Discovery fails because mock server returns empty list
        discover_script = os.path.join(SKILL_DIR, "scripts", "discover-target.py")
        code = f"""
import sys
from importlib.machinery import SourceFileLoader
dt = SourceFileLoader('discover_target', r'{discover_script}').load_module()
dt.discover_target(port=9222, timeout=3)
"""
        d_ret, d_stdout, d_stderr = run_script_with_timeout(["-c", code], timeout=8)
        print(f"Discovery return code under port conflict: {d_ret}")
        assert d_ret == 1, "Discovery should fail/timeout when port 9222 is hijacked"
        
        # 4. Clean up Qt app using stop-app.py
        s_ret, s_stdout, s_stderr = run_script_with_timeout([stop_script, str(pid)], timeout=8)
        print(f"Stop app return code: {s_ret}")
        print(f"Stop app stdout:\n{s_stdout.strip()}")
        assert not os.path.exists("qt_app.pid"), "qt_app.pid should be removed"
        print(">>> RESULT: PASS (App launched, conflict detected, process cleanly isolated and stopped).")
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.5)

if __name__ == "__main__":
    test_timeout_no_port()
    test_occupied_port_invalid_json()
    test_occupied_port_empty_list()
    test_occupied_port_non_page_targets()
    test_occupied_port_http_errors()
    test_occupied_port_raw_garbage_tcp()
    test_launch_with_occupied_port()
    print("\n=======================================================")
    print("ALL 7 PORT CONFLICT & TIMEOUT SCENARIOS PASSED!")
    print("=======================================================")
