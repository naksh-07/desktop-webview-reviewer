# Architecture Document 16: Observation Model

**Document ID:** `docs/architecture/16_OBSERVATION_MODEL.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Target Repository:** `desktop-webview-reviewer`  

---

## 1. The Observation Modality Comparison

A universal desktop automation platform has access to multiple perception channels. Each modality possesses fundamental strengths and catastrophic failure modes:

```
Perception Modality Comparison
┌──────────────────────┬─────────────┬────────────┬─────────────┬────────────────────────────────────────────────────────┐
│ Modality             │ Token Cost  │ Latency    │ Fidelity    │ Primary Failure Mode / Blindspot                       │
├──────────────────────┼─────────────┼────────────┼─────────────┼────────────────────────────────────────────────────────┤
│ 1. Raw Web DOM (HTML)│ 15k–50k     │ 50–150ms   │ Low-level   │ Token blowout; script/style noise; shadow DOM traps    │
│ 2. Web A11y Tree     │ 200–500     │ 20–50ms    │ High-level  │ Pruned of styling; requires semantic markup            │
│ 3. Native Win32 Tree │ <100        │ <5ms       │ Shell-only  │ 100% blind to windowless controls (WPF, WinUI, Web)    │
│ 4. Native UIA3 Tree  │ 500–2,000   │ 50–200ms   │ Semantic    │ Chromium lazy a11y freeze; virtualized control delay   │
│ 5. Full Screenshot   │ 1,500–5,000 │ 100–300ms  │ Pure Visual │ Coordinate hallucination; zero DOM/role introspection  │
│ 6. Visual OCR / BBox │ 1,000–3,000 │ 500–1,500ms│ Approximate │ Text bounding box jitter; fails on icons/toolbars      │
└──────────────────────┴─────────────┴────────────┴─────────────┴────────────────────────────────────────────────────────┘
```

---

## 2. Core Observation Strategy: Dual-Perspective Grounding

Rather than forcing native and webview structures into a single fake "Universal Tree" (Architecture G), the platform exposes **two synchronized perspectives grounded in physical reality**:

```
Dual-Perspective Observation Topology
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                             PHYSICAL DISPLAY (1920x1080)                                 │
│                                                                                          │
│  ┌───────────────────────────── NATIVE SHELL (HWND: 0x004A12) ────────────────────────┐  │
│  │ Title: "StudyLab - Biology Deck" | Visible: True | Cloaked: False                  │  │
│  │ Win32 Bounds: [100, 100, 1280, 800] | Per-Monitor V2 DPI: 1.25 (125%)             │  │
│  │                                                                                    │  │
│  │  [Native MenuBar]  File   Edit   View   Tools   Help                               │  │
│  │   └─ [ref=n1e1] Menu "File"                                                        │  │
│  │   └─ [ref=n1e2] Menu "Edit"                                                        │  │
│  │                                                                                    │  │
│  │  ┌───────────────────── EMBEDDED WEBVIEW (HWND: 0x004A18) ──────────────────────┐  │  │
│  │  │ Host Control: "Chrome_RenderWidgetHostHWND" | CDP Target: "page_873"          │  │  │
│  │  │ Viewport: [100, 160, 1260, 720]                                               │  │  │
│  │  │                                                                               │  │  │
│  │  │   <h1>Cellular Mitosis</h1>                                                   │  │  │
│  │  │   <button class="btn-primary">Start Quiz</button>                             │  │  │
│  │  │    └─ [ref=w1e1] Button "Start Quiz" [focused]                                │  │  │
│  │  │   <input type="text" placeholder="Enter answer" />                            │  │  │
│  │  │    └─ [ref=w1e2] Textbox "Enter answer"                                       │  │  │
│  │  │                                                                               │  │  │
│  │  └───────────────────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                                    │  │
│  │  [Native StatusBar] Ready | Memory: 42MB                                           │  │
│  │   └─ [ref=n1e3] Status "Ready"                                                     │  │
│  └────────────────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Native Perspective (`perspective="native"`):**
   * Generated via the .NET FlaUI worker using `CacheRequest` over unmanaged UIA3.
   * Identifies outer window chrome, menu bars, modal dialogs, status bars, and system tray popups.
   * Uses reference prefix `n` (e.g., `n1e1`, `n1e2`).
2. **Webview Perspective (`perspective="webview"`):**
   * Generated via direct CDP query to `Accessibility.getFullAXTree` with `interestingOnly: true`.
   * Strips away hundreds of non-semantic `<div>` and `<span>` layout containers, formatting only actionable controls (`button`, `link`, `textbox`, `combobox`, `heading`).
   * Uses reference prefix `w` (e.g., `w1e1`, `w1e2`).
3. **Cross-Boundary Synchronization:**
   * The Native Supervisor captures the webview container's physical screen rectangle.
   * When the agent interacts with webview ref `w1e1`, coordinates are calculated relative to the webview viewport and dispatched via CDP `Input.dispatchMouseEvent`.
   * Native OS menus are interacted with via `n1e1` dispatched through UIA/Win32.

---

## 3. The Snapshot Format & Semantic Compression

### 3.1 Compact YAML Representation
Raw DOM trees consume 20,000–50,000 tokens. The Observation Engine transforms the accessibility tree into an indented, token-efficient YAML format (200–400 tokens):

```yaml
- window: "StudyLab - Biology Deck" [hwnd=303492] [focused]
  - menubar:
    - menuitem "File" [ref=n1e1]
    - menuitem "Edit" [ref=n1e2]
  - webview: [target=page_873] [bounds=100,160,1260,720]
    - heading "Cellular Mitosis" [level=1]
    - paragraph "Phase 1: Prophase review."
    - button "Start Quiz" [ref=w1e1] [role=button]
    - textbox "Enter answer" [ref=w1e2] [placeholder="Type here..."]
    - checkbox "Show hints" [ref=w1e3] [checked=false]
  - statusbar:
    - text "Ready" [ref=n1e3]
```

### 3.2 Token Efficiency Rules
1. **Omit Non-Actionable Layout Nodes:** Pure styling containers with no accessible name, role, or event listener are collapsed.
2. **Sequential Ref Compaction:** Refs are generated as short alphanumeric strings (`w1e1` to `w1e99`), saving up to 70% of locator token overhead compared to long CSS or XPath selectors.
3. **Attribute Minification:** Only interactive state flags (`[checked]`, `[disabled]`, `[focused]`, `[expanded]`) are emitted.

---

## 4. Differential Snapshots (`kind=diff`)

Track 01 demonstrated that incremental UI diff snapshots achieve an **84% to 96% reduction in context token consumption**.

### 4.1 Diff Mechanism
The Observation Engine maintains an in-memory tree hash of the previous epoch. When `diff_only: true` is requested:
1. Node identities are tracked across epochs by semantic signature: `(role, accessible_name, locator_path)`.
2. Nodes with identical signatures and states are omitted.
3. Mutated, added, or removed nodes are emitted using standard diff syntax:

```yaml
# Observation Epoch: 2 (Diff from Epoch 1)
@@ webview: [target=page_873] @@
- button "Start Quiz" [ref=w1e1]
+ button "Stop Quiz" [ref=w2e1] [role=button]
+ timer "00:59" [ref=w2e2]
~ textbox "Enter answer" [ref=w2e3] [focused]
```

---

## 5. Large Tree Handling & Subtree Pagination

Dense enterprise applications (e.g., medical software, CAD, dense spreadsheets) can contain >5,000 nodes, causing context window blowout even in accessibility representations.

### 5.1 Bounded Depth & Subtree Scoping
1. **Default Depth Limiting:** The root snapshot evaluates to a default depth of `max_depth: 5`.
2. **Container Pruning:** Virtualized list views or data grids containing >20 items emit only the first 5 visible items followed by a pagination indicator:
   ```yaml
   - list "Student Records" [total_items=450]:
     - listitem "Alice Smith" [ref=w1e10]
     - listitem "Bob Jones" [ref=w1e11]
     - listitem "Charlie Brown" [ref=w1e12]
     - text "... 447 more items (scroll or query to inspect) ..."
   ```
3. **Subtree Querying:** The tool `desktop_inspect` supports scoping to a specific subtree:
   `desktop_inspect(session_id="s1", root_ref="w1e10")`.

---

## 6. Observation Error Recovery

If the target webview is loading or undergoing rapid CSS re-rendering:
* The Observation Engine triggers `waitForStableDom` in the utility world, sampling DOM mutation settling over two consecutive animation frames (100ms interval).
* If settling fails within 2,000ms, the snapshot is emitted with a warning annotation: `[warning="Layout actively animating; refs may be volatile"]`.
