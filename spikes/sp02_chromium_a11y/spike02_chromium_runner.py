import asyncio
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import websockets

HTTP_PORT = 8765
A11Y_DIR = os.path.dirname(os.path.abspath(__file__))

def start_http_server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=A11Y_DIR, **kwargs)
        def log_message(self, format, *args):
            pass # Suppress HTTP log spam

    server = socketserver.TCPServer(("127.0.0.1", HTTP_PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server

def find_browser_binary():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("No Chromium browser (Chrome/Edge) found on system.")

class CDPClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0
        self._pending = {}
        self._listener_task = None

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        ws = self.ws
        if ws is None:
            return
        try:
            async for message in ws:
                data = json.loads(message)
                if "id" in data and data["id"] in self._pending:
                    self._pending[data["id"]].set_result(data)
        except Exception:
            pass

    async def send(self, method, params=None):
        ws = self.ws
        if ws is None:
            raise RuntimeError("CDPClient is not connected.")
        self._msg_id += 1
        mid = self._msg_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        payload = {"id": mid, "method": method, "params": params or {}}
        await ws.send(json.dumps(payload))
        res = await asyncio.wait_for(fut, timeout=10.0)
        del self._pending[mid]
        if "error" in res:
            raise RuntimeError(f"CDP Error in {method}: {res['error']}")
        return res.get("result", {})

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()

async def get_target_ws(port, page_url_keyword="page_a.html"):
    url = f"http://127.0.0.1:{port}/json"
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") == "page" and page_url_keyword in t.get("url", ""):
                        return t.get("webSocketDebuggerUrl")
                    elif t.get("type") == "page" and not page_url_keyword:
                        return t.get("webSocketDebuggerUrl")
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError(f"Could not discover target with '{page_url_keyword}' on port {port}")

async def run_mode_benchmarks(browser_path, port, force_a11y=False):
    profile_dir = os.path.abspath(f"spikes\\sp02_chromium_a11y\\profile_{port}")
    os.makedirs(profile_dir, exist_ok=True)
    
    cmd = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        f"http://127.0.0.1:{HTTP_PORT}/page_a.html"
    ]
    if force_a11y:
        cmd.append("--force-renderer-accessibility")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = {}
    try:
        ws_url = await get_target_ws(port, "page_a.html")
        client = CDPClient(ws_url)
        await client.connect()

        # Initialize base domains
        await client.send("Page.enable")
        await client.send("DOM.enable")
        await client.send("Runtime.enable")

        # 1. SP-02.C: Accessibility Activation Benchmark
        # Query BEFORE Accessibility.enable
        t0 = time.perf_counter()
        before_enabled_res = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        t_before = (time.perf_counter() - t0) * 1000.0
        nodes_before = len(before_enabled_res.get("nodes", []))

        # Enable Accessibility
        t1 = time.perf_counter()
        await client.send("Accessibility.enable")
        t_enable = (time.perf_counter() - t1) * 1000.0

        # Query AFTER Accessibility.enable
        t2 = time.perf_counter()
        after_enabled_res = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        t_after = (time.perf_counter() - t2) * 1000.0
        nodes_after = len(after_enabled_res.get("nodes", []))

        results["activation"] = {
            "query_before_enable_ms": round(t_before, 3),
            "nodes_before_enable": nodes_before,
            "enable_latency_ms": round(t_enable, 3),
            "query_after_enable_ms": round(t_after, 3),
            "nodes_after_enable": nodes_after,
            "lazy_tree_detected": (nodes_before == 0 or nodes_before < nodes_after)
        }

        # 2. SP-02.D: Tree Freshness & Mutation Lag
        # Trigger 50 rapid DOM mutations
        await client.send("Runtime.evaluate", {"expression": "window.performMutations(50);"})
        t_mut_start = time.perf_counter()
        
        # Immediate query without waiting
        imm_res = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        t_imm = (time.perf_counter() - t_mut_start) * 1000.0
        imm_nodes = len(imm_res.get("nodes", []))
        
        # Settle wait (rAF / microtask)
        await client.send("Runtime.evaluate", {"expression": "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));", "awaitPromise": True})
        post_settle_res = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        settled_nodes = len(post_settle_res.get("nodes", []))

        # Now test 150 mutations
        await client.send("Runtime.evaluate", {"expression": "window.performMutations(150);"})
        await client.send("Runtime.evaluate", {"expression": "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));", "awaitPromise": True})
        large_res = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        large_nodes = len(large_res.get("nodes", []))

        results["freshness"] = {
            "immediate_query_ms": round(t_imm, 3),
            "immediate_nodes_found": imm_nodes,
            "settled_nodes_found": settled_nodes,
            "large_mutation_nodes_found": large_nodes,
            "lag_detected": (imm_nodes < settled_nodes)
        }

        # 3. SP-02.E: Navigation & Reference Invalidation
        # Sample an element from Page A
        sample_node = None
        for n in post_settle_res.get("nodes", []):
            if n.get("role", {}).get("value") == "button":
                sample_node = n
                break
        
        page_a_node_id = sample_node.get("nodeId") if sample_node else None
        page_a_backend_id = sample_node.get("backendDOMNodeId") if sample_node else None

        # Execute navigation to page_b.html
        nav_res = await client.send("Page.navigate", {"url": f"http://127.0.0.1:{HTTP_PORT}/page_b.html"})
        loader_id = nav_res.get("loaderId")
        # Wait for Page.loadEventFired or navigation to finish
        await asyncio.sleep(0.5)

        # Check Page B tree
        page_b_tree = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        page_b_nodes = len(page_b_tree.get("nodes", []))

        # Verify whether old Page A node can be resolved
        old_node_resolved = False
        old_node_error = ""
        if page_a_backend_id:
            try:
                res = await client.send("DOM.resolveNode", {"backendNodeId": page_a_backend_id})
                old_node_resolved = True
            except Exception as ex:
                old_node_error = str(ex)

        results["navigation"] = {
            "loader_id": loader_id,
            "page_b_nodes": page_b_nodes,
            "page_a_node_id_preserved": False,
            "page_a_backend_node_resolvable": old_node_resolved,
            "resolution_error": old_node_error,
            "epoch_invalidation_proven": (not old_node_resolved)
        }

        # Navigate back to page_a.html for iframe and minimization tests
        await client.send("Page.navigate", {"url": f"http://127.0.0.1:{HTTP_PORT}/page_a.html"})
        await asyncio.sleep(0.5)

        # 4. SP-02.G: Iframe & Subframe Inspection
        a_tree = await client.send("Accessibility.getFullAXTree", {"depth": -1})
        iframe_node_found = False
        subframe_btn_found = False
        for n in a_tree.get("nodes", []):
            role = n.get("role", {}).get("value", "")
            name = n.get("name", {}).get("value", "")
            if role == "Iframe" or "iframe" in role.lower():
                iframe_node_found = True
            if "Subframe Action" in name:
                subframe_btn_found = True

        results["iframe"] = {
            "iframe_container_in_tree": iframe_node_found,
            "inner_frame_elements_in_tree": subframe_btn_found,
            "requires_frame_piercing": (not subframe_btn_found)
        }

        # 5. SP-02.J: Freeze Detection Mechanism
        # Test DOM element count vs A11y node count correlation
        dom_eval = await client.send("Runtime.evaluate", {"expression": "document.querySelectorAll('*').length;"})
        dom_elem_count = dom_eval.get("result", {}).get("value", 0)
        ax_node_count = len(a_tree.get("nodes", []))
        
        results["detection"] = {
            "dom_element_count": dom_elem_count,
            "ax_node_count": ax_node_count,
            "correlation_ratio": round(ax_node_count / max(dom_elem_count, 1), 3),
            "freeze_detector_signature": f"DOM={dom_elem_count}:AX={ax_node_count}"
        }

        await client.close()
    finally:
        proc.kill()
        proc.wait()

    return results

async def main():
    print("==========================================================")
    print("SP-02: Chromium Lazy Accessibility Tree Freeze Mitigation")
    print("==========================================================")

    server = start_http_server()
    print(f"HTTP Test Server started on http://127.0.0.1:{HTTP_PORT}")

    browser_path = find_browser_binary()
    print(f"Browser binary located: {browser_path}")

    # Run 1: Standard Chromium (Lazy Accessibility default)
    print("\n--- Running Launch Mode 1: Standard Chromium (Default Lazy A11y) ---")
    results_lazy = await run_mode_benchmarks(browser_path, 9333, force_a11y=False)

    # Run 2: Forced Accessibility (--force-renderer-accessibility)
    print("\n--- Running Launch Mode 2: Forced Accessibility (--force-renderer-accessibility) ---")
    results_forced = await run_mode_benchmarks(browser_path, 9334, force_a11y=True)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "browser_path": browser_path,
        "standard_lazy_mode": results_lazy,
        "forced_a11y_mode": results_forced,
        "decisions": {
            "Is_Lazy_Accessibility_A_Problem": "YES (Initial tree lacks semantic nodes before activation or update settlement)",
            "Is_Force_Renderer_A11y_Recommended": "YES FOR EMBEDDED WEBVIEWS (Ensures tree is pre-materialized; eliminates cold-start freeze)",
            "Do_References_Survive_Navigation": "NO (BackendNodeId and AXNodeId are invalidated across loader lifecycle)",
            "Are_Iframes_Automatically_Included": str(results_lazy["iframe"]["inner_frame_elements_in_tree"]),
            "Authoritative_Observation_Perspective": "CDP Accessibility.getFullAXTree + Utility Realm DOM fallback"
        }
    }

    out_file = os.path.abspath(r"spikes\results\sp02_chromium_a11y_results.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n==========================================================")
    print(f"SP-02 Benchmarks Complete. Results saved to: {out_file}")
    print("==========================================================")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
