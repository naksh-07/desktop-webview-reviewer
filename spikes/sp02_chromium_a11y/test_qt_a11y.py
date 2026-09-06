import asyncio
import json
import os
import subprocess
import time
import urllib.request
import websockets
from pathlib import Path

ANKI_MATHS_DIR = Path(r"c:\Users\Suraj\Documents\Antigravity\Anki-maths")
ANKI_PYTHON = ANKI_MATHS_DIR / "out" / "pyenv" / "Scripts" / "python.exe"
ANKI_ENTRY = ANKI_MATHS_DIR / "tools" / "run.py"

async def test_anki_a11y():
    if not ANKI_PYTHON.exists():
        print(f"Anki python not found at {ANKI_PYTHON}")
        return {"anki_found": False}

    port = 9255
    cmd = [str(ANKI_PYTHON), str(ANKI_ENTRY), "--port", str(port)]
    env = os.environ.copy()
    env["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)
    
    proc = subprocess.Popen(cmd, env=env, cwd=str(ANKI_MATHS_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Launched Anki Maths (PID {proc.pid}) on port {port}...")
    
    target_ws = None
    target_info = None
    for i in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") == "page" and "main webview" in t.get("title", "").lower():
                        target_ws = t.get("webSocketDebuggerUrl")
                        target_info = t
                        break
                    elif t.get("type") == "page" and not target_ws:
                        target_ws = t.get("webSocketDebuggerUrl")
                        target_info = t
                if target_ws and target_info is not None:
                    print(f"Discovered QtWebEngine Page: {target_info.get('title')} -> {target_ws}")
                    break
        except Exception:
            pass
        await asyncio.sleep(0.5)

    results = {"anki_found": True, "pid": proc.pid, "cdp_bound": (target_ws is not None)}
    if target_ws:
        try:
            ws = await websockets.connect(target_ws, max_size=50 * 1024 * 1024)
            await ws.send(json.dumps({"id": 1, "method": "Accessibility.enable"}))
            resp1 = json.loads(await ws.recv())
            
            t0 = time.perf_counter()
            await ws.send(json.dumps({"id": 2, "method": "Accessibility.getFullAXTree", "params": {"depth": -1}}))
            resp2 = json.loads(await ws.recv())
            t_tree = (time.perf_counter() - t0) * 1000.0
            
            nodes = resp2.get("result", {}).get("nodes", [])
            if target_info is not None:
                results["qtwebengine_target_title"] = target_info.get("title")
            results["qtwebengine_a11y_latency_ms"] = round(t_tree, 3)
            results["qtwebengine_a11y_nodes"] = len(nodes)
            print(f"QtWebEngine AX Tree: {len(nodes)} nodes retrieved in {t_tree:.2f}ms")
            await ws.close()
        except Exception as ex:
            results["qt_error"] = str(ex)
            print(f"QtWebEngine error: {ex}")

    proc.kill()
    proc.wait()
    return results

if __name__ == "__main__":
    res = asyncio.run(test_anki_a11y())
    print("QtWebEngine Test Results:", json.dumps(res, indent=2))
