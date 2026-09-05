# Architecture Document 25: Evidence Contract 2.0 & Forensic Verification

**Document ID:** `docs/architecture/25_EVIDENCE_CONTRACT_2.0.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Architecture H Foundation, Doc 18, Phase 6 Implementation

---

## 1. Executive Summary

In autonomous software testing and review, an unverified test report is worthless. If an agent states "The login workflow passed", a human engineer or automated compliance pipeline must be able to independently audit the cryptographic and physical evidence proving that assertion.

Desktop WebView Reviewer 2.0 formalizes the **Evidence Contract 2.0**. Every observation, screenshot, DOM snapshot, and verification verdict is captured as an immutable, content-addressed artifact stored under cryptographic hashes (SHA-256) and referenced via strict MCP resource URIs (`evidence://{session_id}/{artifact_id}`).

---

## 2. The Evidence Artifact Contract

Every forensic artifact collected by Reviewer conforms to the following schema:

```yaml
evidence_artifact:
  artifact_id: "art_sc_post_01J8F"
  session_id: "sess_01J8F"
  action_id: "act_click_save_99"
  observation_epoch: 4
  timestamp: 1725541800.520

  provenance:
    source_plane: "PHYSICAL_GDI"
    capture_method: "PrintWindow"
    native_hwnd: "0x000A0452"
    target_id: "w1e7"
    dpi_scaling: 1.5

  integrity:
    algorithm: "SHA-256"
    hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    byte_size: 142850
    mime_type: "image/png"
    storage_relpath: "screenshots/post_action_01J8F.png"

  claims_supported:
    - "TargetWasPhysicallyVisible"
    - "ExpectedStateOccurred"

  verdict_impact: "PASS"
```

---

## 3. The 2.0 Evidence Package Structure

At the conclusion of an action sequence, test scenario, or review session, Reviewer compiles an **Authoritative Evidence Package**:

```
EvidencePackage (evidence_manifest.json)
├── Session Metadata (OS, Platform, DWM state, DPI, Engine Info)
├── Process Telemetry (Binary path, PID, creation_time, exit code)
├── Execution Timeline (Synchronized monotonic trace events)
├── Visual Captures:
│   ├── Baseline Pre-Action Screenshot + Hash
│   ├── Post-Action Settlement Screenshot + Hash
│   └── Cropped Affordance Region + Hash
├── Structural Snapshots:
│   ├── Native Win32 Window Hierarchy + Extended Frame Bounds
│   ├── Chromium DOM Tree Snapshot + Computed Styles
│   └── Blink Accessibility Tree (AXTree)
├── Stream Captures:
│   ├── Application stdout / stderr
│   ├── Chromium Console Log Stream
│   └── Network Request Logs (where supported)
├── Forensic Claims Ledger:
│   ├── Claim: ActionWasDispatched (Receipt confirmed)
│   ├── Claim: TargetWasPhysicallyVisible (DWM uncloaked, Z-order unoccluded)
│   └── Claim: ExpectedStateOccurred (Delta observed)
└── Final Cryptographic Signature:
    ├── Root Merkle / Combined SHA-256 Digest
    └── Verification Verdict: PASS | FAIL | UNVERIFIED
```

---

## 4. Tamper Resistance & Immutability Rules

1. **Strict Directory Confinement:** All evidence files are written strictly to isolated session directories within `<workspace>/evidence/{session_id}/`. Relative path traversal (`../`) is rejected at the API boundary.
2. **Byte-Level Verification:** When an agent or external tool requests an evidence artifact via `desktop_get_evidence`, the runtime recalculates the SHA-256 hash of the on-disk file and compares it to the manifest. Any discrepancy immediately raises an `EvidenceIntegrityException`.
3. **Immutability:** Once written and sealed in an epoch manifest, an evidence artifact is immutable. The runtime never overwrites existing screenshots or log files in place.

---

## 5. The Tripartite Verdict Philosophy

Reviewer enforces the strict epistemological standard established in Phase 6:

```
┌─────────────────────────────────────────────────────────────┐
│                    PROOF LEVEL REQUIREMENTS                 │
├────────────────────────────────┬────────────────────────────┤
│ LEVEL 0: DISPATCH ONLY         │ Always yields UNVERIFIED.  │
│                                │ Proves input was sent.     │
├────────────────────────────────┼────────────────────────────┤
│ LEVEL 1: TARGET PRESENT        │ Proves target was found.   │
│                                │ Yields UNVERIFIED.         │
├────────────────────────────────┼────────────────────────────┤
│ LEVEL 2: STATE CHANGE OBSERVED │ Proves app state mutated.  │
│                                │ Conditional PASS / FAIL.   │
├────────────────────────────────┼────────────────────────────┤
│ LEVEL 3: DUAL-PERSPECTIVE      │ Proves DOM + Physical DWM  │
│          CONFIRMATION          │ agree on outcome. PASS.    │
├────────────────────────────────┼────────────────────────────┤
│ LEVEL 4: FORENSIC SEALED       │ Cryptographically sealed   │
│          COMPLETE              │ evidence package. PASS.    │
└────────────────────────────────┴────────────────────────────┘
```

Never can an action be promoted to `PASS` based on assumptions. If proof is missing or ambiguous, the outcome is honestly reported as `UNVERIFIED`.
