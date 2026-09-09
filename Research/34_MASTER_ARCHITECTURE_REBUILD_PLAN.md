# Desktop WebView Reviewer 2.0 — Master Architecture Rebuild Plan

> Status: Architecture source of truth
> Scope: forensic verification, physical-desktop truth, evidence integrity, MCP security, persistence, specialists, recovery, concurrency, Windows-native reality, testing, and release gates.

## 0. Mission

Build a reviewer whose PASS means only what the canonical verifier can prove. The system must prefer `UNVERIFIED` over a false `PASS` and must have exactly one certifying authority.

## 1. Target Architecture

```text
Mission / Request
      |
      v
Capability + Policy Admission
      |
      +------------------------------+
      |                              |
      v                              v
Logical WebView Plane          Native OS Plane
(CDP/WebView APIs)             (Win32/process/session/input)
      |                              |
      +---------------+--------------+
                      v
              PhysicalTruthAuthority
                      |
             DesktopCaptureManager
             /       |        \
          GDI      DXGI/WGC   Diagnostic
                      |
                      v
                EvidenceFactory
                      |
              Evidence Envelope
                      |
              ClaimVerifier
                      |
                  Verdict
              /      |       \
            PASS  FAIL  UNVERIFIED
                      |
                 EvidenceStore
```

No secondary component may synthesize a certifying PASS.

## 2. Five Evidence Planes

1. Logical state: DOM, CDP, WebView runtime state.
2. Native OS state: HWND, PID, process incarnation, session, foreground, desktop, bounds, cloaking, z-order.
3. Physical desktop pixels: pixels observed from an approved desktop-surface capture backend.
4. Interaction receipt: OS input submission and application-level postcondition are separate facts.
5. Artifact integrity: immutable evidence metadata, SHA-256, timestamps, versioning, and optional append-only hash chaining.

## 3. Claim-Driven Verification

Verification profiles must be explicit:

- `VISIBLE_ON_DESKTOP`: target is physically visible, not necessarily foreground.
- `FOREGROUND_ON_DESKTOP`: visible + foreground.
- `INTERACTIVE_DESKTOP`: foreground + active interactive session + usable input desktop + unlocked state where observable.
- `ACTION_COMPLETED`: action attempt + receipt + postcondition.
- `ACTION_RESULT_PHYSICALLY_VISIBLE`: completed action + physical post-action proof.

A screenshot alone is never a universal proof.

## 4. Authority Graph Rules

The canonical path is:

`TargetManager -> NativeOSSupervisor -> PhysicalTruthAuthority -> EvidenceFactory -> ClaimVerifier -> EvidenceStore`

Required work:

- inventory every PASS/FAIL/UNVERIFIED producer;
- inventory every evidence constructor and capture producer;
- inventory CLI, MCP, specialist, recovery, and legacy paths;
- remove or demote every alternate PASS sink;
- make legacy diagnostics incapable of certification.

Deliverables: `AUTHORITY_GRAPH.md`, `PASS_SINKS.md`, `CURRENT_ARCHITECTURE_GAP_ANALYSIS.md`, and a migration dependency map.

## 5. Domain Model

Introduce explicit types/envelopes for:

- `Claim`
- `VerificationProfile`
- `TargetIdentity`
- `ProcessIdentity`
- `ProcessIncarnation`
- `EvidenceEnvelope`
- `EvidenceType`
- `EvidenceTrust`
- `CaptureReceipt`
- `FailureCode`
- `VerificationResult`

Evidence is data. Verification derives verdicts. Callers never provide certifying fields as trusted facts.

## 6. Identity Hardening

Bind every certifying observation to:

- HWND
- PID
- process creation time captured independently
- process executable identity where available
- session ID
- target discovery timestamp
- request/mission/claim/action/attempt IDs

Process creation time must be anchored when the target is first admitted/discovered, not freshly fetched at the moment of a later capture. PID recycling must therefore fail closed.

## 7. PhysicalTruthAuthority

Create one canonical service responsible for physical truth. It must independently observe OS state and capture pixels. Missing or ambiguous authoritative fields result in `UNVERIFIED`.

Important observations include:

- HWND ownership
- process identity/incarnation
- session and interactive desktop
- foreground state when required by the claim
- visibility/cloaking
- extended frame bounds
- monitor intersection
- z-order/occlusion
- capture coverage
- capture timestamp
- capture backend and capability

Do not equate `IsWindowVisible` with physical visibility. Do not equate foreground with all forms of visibility.

## 8. Capture Architecture

Use a `DesktopCaptureManager` with pluggable backends and a capability matrix. Candidate backends may include GDI desktop capture, DXGI Desktop Duplication, and Windows Graphics Capture. They must be empirically certified against the project's contract before becoming certifying backends.

`PrintWindow`, HWND/window-DC captures, CDP screenshots, WebView screenshots, Playwright screenshots, and offscreen/hidden rendering are diagnostic unless a backend independently satisfies the physical-desktop certification contract.

Do not blindly replace GDI with WGC. Capture technology is an implementation detail; the certification contract is the authority.

## 9. Visibility, Occlusion, and Protected Capture

Physical visibility is a claim-specific computation using native geometry, z-order, clipping/occlusion evidence, compositor state where available, and desktop pixels.

Model capture coverage explicitly:

- `VISIBLE_IN_CAPTURE`
- `EXCLUDED_FROM_CAPTURE`
- `UNKNOWN`

A protected/excluded window cannot be declared physically absent merely because it is missing from captured pixels. Ambiguity must become `UNVERIFIED`.

## 10. Foreground and Input

Foreground is an OS observation, not a boolean supplied by the caller. Input insertion is not application success.

For interactive claims, independently verify the relevant session, input desktop, foreground relationship, and action postcondition.

## 11. MCP Security

MCP is a control plane, not a trust boundary.

Required controls:

- explicit capability authorization;
- request IDs and replay protection where appropriate;
- audit trail;
- scoped process execution;
- executable/argument/working-directory/environment/filesystem/network policy instead of naive `cmd.exe` blocklists;
- explicit restriction of main-world JavaScript execution;
- DOM mutation classified as `PROGRAMMATIC_STATE_CHANGE`, never physical input proof;
- destructive-action policy with user confirmation/admission;
- prompt-injection boundary between page content and agent/tool instructions.

`desktop_evaluate(in_main_world=True)` must not be an unrestricted escape hatch.

## 12. Destructive Actions

Destructive operations require an explicit policy decision and, where required, user confirmation before execution. The action engine must classify actions rather than relying on documentation claims.

Every action gets an `action_id` and every execution attempt gets an `attempt_id`. Failed attempts are retained and never overwritten.

## 13. Evidence Lifecycle

```text
RAW -> OBSERVED -> VALIDATED -> SEALED -> CERTIFIABLE
```

Certifying fields are derived from trusted observers. No caller-created `PhysicalDesktopEvidence` object can make itself authoritative by setting `is_authoritative=True`.

Safe defaults:

- verdict = `UNVERIFIED`
- authority = false until proven
- post-capture validation = false until proven
- empty artifact path is non-certifying
- missing HWND/PID/session/incarnation data is non-certifying

## 14. Artifact Integrity

Store evidence outside the working directory, under application-managed evidence storage. Use SHA-256 content hashes and immutable metadata. Optional hash chaining may link each sealed record to the previous record. Blockchain is unnecessary.

Each artifact should record:

- artifact/evidence ID
- request/mission/claim/action/attempt IDs
- creation/capture time
- target identity
- process incarnation
- capture backend/version
- schema/verifier/rule/authority versions
- hash
- provenance
- validation state

## 15. Temporal Binding

Capture and observation must be bound to the same target incarnation and relevant action attempt. A later observation must not silently certify an earlier state.

Use explicit timestamps and sequence/order information. Where freshness cannot be established, return `UNVERIFIED`.

## 16. Database Model

Normalize around:

- `sessions`
- `targets`
- `missions`
- `claims`
- `actions`
- `action_attempts`
- `observations`
- `physical_observations`
- `capture_artifacts`
- `input_receipts`
- `verifications`
- `verification_evidence`

Never overwrite failed attempts. Preserve lineage from request through verdict and artifacts.

Version all schemas/rules that can affect certification.

## 17. Manifest

The evidence manifest must default to `UNVERIFIED`. A manifest is a sealed index, not a verdict oracle.

The canonical verifier derives the final verdict from claims, observations, policy, and evidence. String matching such as `"win32_gdi_hwnd" in source` must not decide trust.

## 18. State Machines

Define explicit state machines for:

- target lifecycle
- mission lifecycle
- action lifecycle
- attempt lifecycle
- evidence lifecycle
- verification lifecycle

Illegal transitions must be rejected and observable.

## 19. Recovery and Concurrency

Recovery must preserve evidence lineage. Retries create new attempts, not replacement records. Concurrent work must use stable IDs and transaction boundaries. A stale observation cannot silently satisfy a new claim.

## 20. Coordinate Architecture

Treat logical WebView coordinates, viewport coordinates, client coordinates, screen coordinates, physical pixels, DPI-scaled coordinates, and multi-monitor virtual-desktop coordinates as distinct spaces.

Every coordinate conversion must declare source and destination spaces plus DPI context. Never silently mix them.

## 21. Specialist Architecture

Specialists may inspect, research, diagnose, implement delegated changes, write tests, and review evidence. They may not:

- redefine mission scope;
- weaken verification rules;
- manufacture certifying evidence;
- issue final verdicts outside the canonical verifier;
- bypass authorization;
- delete failed attempts.

Specialist output is advisory or implementation evidence, never authority.

## 22. Testing Strategy

Use multiple layers:

1. Unit tests for identity, trust, state machines, and verdict semantics.
2. Integration tests for MCP and runtime routes.
3. Adversarial tests for PID recycling, HWND reuse, missing fields, forged evidence, stale timestamps, occlusion, cloaking, protected capture, foreground races, DOM spoofing, and malicious launch inputs.
4. Property/state-machine tests where practical.
5. Real Windows physical-lab tests with covered, background, minimized, cloaked, moving, resizing, multi-monitor, DPI, locked-session, RDP, and protected-window scenarios.
6. Independent final forensic audit.

## 23. Physical Capture Laboratory

Build a repeatable Windows test matrix. Record environment metadata and expected physical truth. A backend becomes certifying only after passing the matrix for its declared capabilities.

Important rule: a modern API is not automatically a stronger oracle. Measure it.

## 24. Migration Strategy

Migrate in dependency order:

1. Freeze baseline.
2. Close authority graph.
3. Introduce domain types.
4. Harden identity/incarnation.
5. Build PhysicalTruthAuthority.
6. Build capture manager/lab.
7. Build evidence factory/integrity.
8. Build canonical ClaimVerifier.
9. Remove legacy PASS authorities.
10. Harden MCP/action security.
11. Normalize persistence.
12. Integrate specialists/recovery/concurrency.
13. Run adversarial and physical lab tests.
14. Run independent release audit.

Do not perform a broad rewrite before the authority graph and dependency map are understood.

## 25. Acceptance Criteria

Release is blocked unless:

- exactly one certifying PASS authority exists;
- every other path is diagnostic or delegates to the canonical verifier;
- missing/ambiguous authoritative data fails closed;
- PID recycling and HWND reuse cannot yield false PASS;
- capture backend claims are empirically justified;
- physical visibility is claim-specific;
- input submission is distinct from application success;
- evidence is isolated, hashed, versioned, and traceable;
- destructive actions are policy-gated;
- MCP process and JS capabilities are scoped;
- specialist agents cannot bypass authority;
- failed attempts are retained;
- adversarial tests pass;
- real Windows physical tests pass for declared capabilities;
- independent forensic audit finds no known false-PASS path.

## 26. Correctness Definition

The system is correct when every PASS is supported by sufficient evidence for the exact claim and verification profile, every unsupported or contradictory state becomes `UNVERIFIED`, and every evidence artifact can be traced back to the exact request, target incarnation, action attempt, observer, capture backend, and verifier rule that produced the decision.

## 27. Operating Philosophy

The reviewer is not a screenshot generator. It is a claim-verification system operating across two realities: the WebView's logical reality and the operating system's physical reality.

When those realities disagree, neither side automatically wins. The verifier determines whether the requested claim is actually provable. If it is not, the answer is `UNVERIFIED`.
