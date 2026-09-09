# Desktop WebView Reviewer 2.0 — Agent Workforce

## Purpose

This document defines the specialist-agent workforce for the architecture rebuild. Specialists are mandatory delegated reviewers/implementers for the phases where their expertise applies. They do not own certification authority.

## Existing Canonical Specialists

- `Explorer`: repository discovery, code-path mapping, architecture reconnaissance.
- `Tester`: tests, regression, adversarial validation, contract enforcement.
- `RealityInspector`: native/physical desktop reality checks and evidence review.
- `Debugger`: root-cause analysis and failure isolation.
- `EvidenceSpecialist`: evidence collection, lineage, integrity, and forensic review.

Use the repository's actual specialist registry/contracts as the source of truth for names and interfaces.

## Project-Specific Specialist Roles

### 1. `forensic-architecture-auditor`
Mission: reconstruct the actual architecture and authority graph from code, not documentation.

Must inspect:
- every PASS/FAIL/UNVERIFIED producer;
- every evidence constructor;
- every capture producer;
- CLI/MCP/specialist/recovery routes;
- legacy paths and aliases;
- documentation/code contradictions.

Output: authority graph, PASS sink inventory, contradiction list, dependency map.

### 2. `windows-physical-forensics`
Mission: audit the Windows-native physical truth model.

Must inspect:
- HWND/PID ownership;
- process incarnation and creation time;
- session and interactive desktop;
- foreground state;
- visibility/cloaking;
- extended frame bounds;
- z-order and occlusion;
- DPI/multi-monitor behavior;
- native input constraints.

Output: native observation contract, failure modes, Windows test matrix.

### 3. `capture-lab-engineer`
Mission: design and validate physical desktop capture backends.

Must inspect/test where possible:
- GDI desktop capture;
- DXGI Desktop Duplication;
- Windows Graphics Capture;
- protected/excluded capture behavior;
- covered/background/minimized/cloaked windows;
- moving/resizing and multi-monitor cases;
- RDP/desktop-switch failure behavior.

Output: backend capability matrix and empirical certification criteria.

### 4. `evidence-integrity-guardian`
Mission: make evidence non-forgeable by ordinary callers and preserve forensic lineage.

Must inspect:
- evidence lifecycle;
- trust levels;
- manifest defaults;
- artifact storage;
- hashes;
- timestamps;
- versioning;
- sealing;
- provenance;
- retry/attempt lineage.

Output: evidence envelope contract, integrity rules, migration requirements.

### 5. `mcp-security-redteamer`
Mission: attack the MCP/control plane and prove authorization boundaries.

Must inspect/test:
- main-world JavaScript execution;
- DOM mutation spoofing;
- process launch policy;
- command/argument injection;
- filesystem/network scope;
- destructive actions;
- request IDs/replay behavior;
- prompt-injection boundaries;
- tool authorization.

Output: threat model, exploit cases, security gates, adversarial tests.

### 6. `claim-verification-theorist`
Mission: ensure verdicts correspond to explicit claims and sufficient evidence.

Must inspect:
- verification profiles;
- PASS/FAIL/UNVERIFIED semantics;
- temporal binding;
- contradiction handling;
- evidence sufficiency;
- stale evidence rejection;
- trust derivation.

Output: claim/evidence/verdict rules and formal-ish invariants suitable for tests.

### 7. `runtime-state-concurrency`
Mission: audit lifecycle, recovery, races, and temporal correctness.

Must inspect:
- target lifecycle;
- mission/action/attempt states;
- concurrent requests;
- retries;
- stale observations;
- PID/HWND reuse races;
- transaction boundaries;
- crash recovery.

Output: state-machine model, race cases, recovery contract.

### 8. `database-forensics-engineer`
Mission: design normalized persistence for forensic lineage.

Must inspect:
- sessions;
- targets;
- missions;
- claims;
- actions/attempts;
- observations;
- physical observations;
- capture artifacts;
- input receipts;
- verifications;
- verification/evidence links;
- schema migration/versioning.

Output: schema proposal, constraints, indexes, migration plan.

### 9. `release-forensic-auditor`
Mission: perform the independent final certification audit.

Must inspect:
- all authority paths;
- all declared certifying backends;
- adversarial tests;
- security gates;
- evidence integrity;
- documentation/code consistency;
- packaging/release state.

Output: independent PASS/FAIL/UNVERIFIED release recommendation based only on the canonical verifier and acceptance criteria.

## Mandatory Agent Invocation Matrix

| Phase | Mandatory specialists |
|---|---|
| 0 Baseline | Explorer, forensic-architecture-auditor |
| 1 Authority Graph | forensic-architecture-auditor, Explorer, RealityInspector |
| 2 Domain Model | claim-verification-theorist, evidence-integrity-guardian |
| 3 Identity | windows-physical-forensics, runtime-state-concurrency |
| 4 Physical Truth | windows-physical-forensics, RealityInspector |
| 5 Capture Lab | capture-lab-engineer, windows-physical-forensics, RealityInspector |
| 6 Evidence Factory | evidence-integrity-guardian, claim-verification-theorist |
| 7 Canonical Verifier | claim-verification-theorist, EvidenceSpecialist, Tester |
| 8 Legacy Removal | forensic-architecture-auditor, Explorer, Tester |
| 9 MCP Security | mcp-security-redteamer, Tester |
| 10 Persistence | database-forensics-engineer, runtime-state-concurrency |
| 11 Runtime/Recovery | runtime-state-concurrency, Debugger, Tester |
| 12 Adversarial Tests | mcp-security-redteamer, windows-physical-forensics, claim-verification-theorist, Tester |
| 13 Physical Lab | capture-lab-engineer, windows-physical-forensics, RealityInspector, Tester |
| 14 Release Audit | release-forensic-auditor, forensic-architecture-auditor, EvidenceSpecialist, Tester |

If a named project-specific agent is unavailable in the current environment, the main agent must use the closest available specialist contract and record the substitution. It must never silently pretend that a specialist was invoked.

## Main-Agent Protocol

For every implementation phase:

1. Read `Research/34_MASTER_ARCHITECTURE_REBUILD_PLAN.md`.
2. Read this workforce contract.
3. Identify the phase's mandatory specialists.
4. Invoke those specialists before making architecture-changing decisions.
5. Require each specialist to inspect the actual repository state relevant to its role.
6. Record specialist findings and disagreements.
7. Resolve conflicts against the master plan, actual code, tests, and empirical evidence.
8. Implement only after the architecture gate is satisfied.
9. Run Tester for regression/adversarial validation.
10. Use Debugger when failures require root-cause isolation.
11. Use EvidenceSpecialist for evidence/provenance review.
12. Clean and simplify only after behavior is stable.
13. Update documentation only after implementation truth is known.
14. Do not close a phase until its acceptance criteria and required specialist review are complete.

## Specialist Authority Boundary

Specialists may:

- inspect code;
- search/research;
- diagnose defects;
- implement explicitly delegated changes;
- write tests;
- review evidence;
- propose architecture changes.

Specialists may not:

- redefine mission scope;
- weaken a security or verification rule to make tests pass;
- manufacture certifying evidence;
- directly issue a final certification verdict outside the canonical verifier;
- bypass capability authorization;
- delete failed attempts or hide contradictory evidence;
- turn diagnostic captures into certifying captures without satisfying the capture contract.

## Golden Rule

**Specialist output is evidence for engineering decisions, never the certification authority.**

The canonical ClaimVerifier remains the only component capable of deriving a certifying PASS.
