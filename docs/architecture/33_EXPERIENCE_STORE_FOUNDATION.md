# Architecture Document 33: Experience Store Foundation (Milestone 2.1 Prompt 1)

## 1. What the Experience Store Is
The **Experience Store** is a local, durable, structured historical persistence subsystem for Desktop WebView Reviewer. It records structured review facts, sessions, missions, action references, trace event references, evidence references, and tripartite outcomes (`PASS` / `FAIL` / `UNVERIFIED`) across test sessions.

It acts strictly as a **consumer and persistence layer**. It does NOT replace existing authoritative runtime mechanisms (DesktopTraceEngine, EvidenceStore, VerificationEngine, or SessionManager).

## 2. What It Stores
The store persists structured, schema-versioned relational tables in a local SQLite database:
- **Installation Identity:** Unique persistent installation UUID, runtime version, schema version, creation/update timestamps.
- **Projects:** Project ID, friendly application name, root path.
- **Review Sessions:** Session ID, project association, start/completion times, execution status, target executable, target PID, target HWND, active target plane, and session scope.
- **Review Missions:** Mission ID, goal, scope, start/completion times, execution status.
- **Action References:** Action ID, session ID, action type, plane, target selector, settlement duration, action status, and complete provenance envelope.
- **Trace Event References:** Event ID, session ID, monotonic sequence number, canonical event type, target plane, and provenance envelope.
- **Evidence References:** Evidence ID, session ID, action ID, artifact ID, artifact type, byte-level SHA-256 checksum, relative file URI, and provenance envelope.
- **Experience Outcomes:** Outcome ID, session ID, tripartite verdict (`PASS` / `FAIL` / `UNVERIFIED`), confidence score (0.0 to 1.0), error classification, and detailed diagnostic context.

## 3. What It Explicitly Does NOT Store
Under Section 10 Privacy Boundaries, the Experience Store strictly prohibits and actively blocks:
- **Raw Chain-of-Thought (CoT):** Hidden model reasoning, thinking steps, and internal chain-of-thought traces.
- **Unrestricted Model Transcripts:** Raw LLM prompt archives, conversational message histories, and arbitrary transcript logs.
- **Credentials & Secrets:** Passwords, API keys, bearer tokens, private keys, authentication cookies, and JWTs.
- **Binary Forensic Blobs:** Screenshots, DOM tree dumps, or forensic files are NOT stored as SQLite BLOBs. Large artifacts remain solely in the authoritative Evidence Store, referenced in the Experience Store only via relative path and SHA-256 checksums.
- **Unrestricted Filesystem Dumps:** Individual metadata strings are capped at 32 KB to prevent disk-dump pollution.

## 4. Default Data Directory
On Windows, the default data directory is resolved to the per-user local application data folder:
```text
%LOCALAPPDATA%\DesktopWebViewReviewer\experience
```
- Database file: `%LOCALAPPDATA%\DesktopWebViewReviewer\experience\experience.db`
- Installation metadata: `%LOCALAPPDATA%\DesktopWebViewReviewer\experience\installation_id.json`

On POSIX platforms (Linux / macOS), the fallback path is:
```text
~/.local/share/DesktopWebViewReviewer/experience
```

The default data directory is **never placed inside the source code repository**.

## 5. Custom Directory Configuration & Precedence
The storage directory is resolved following strict precedence:
1. **Explicit Parameter:** `ExperienceConfig(base_dir=...)` passed directly to the store.
2. **Environment Override:** `DESKTOP_REVIEWER_EXPERIENCE_DIR` environment variable.
3. **Platform Default:** `%LOCALAPPDATA%\DesktopWebViewReviewer\experience`.

The resolved path and database health are inspectable via:
```powershell
desktop-reviewer doctor --verbose
desktop-reviewer update doctor
desktop-reviewer update status
```

## 6. Separation Between Experience Data and Forensic Evidence
A strict architectural separation is maintained:
```text
Program Installation  ≠  Experience Data  ≠  Forensic Evidence
(.venv / Scripts)        (%LOCALAPPDATA%)    (evidence/ / user artifacts)
```
- The Experience Store stores structured index records and checksums.
- The Evidence Store stores physical, content-addressed files (PNG screenshots, diffs, JSON receipts).
- Experience records point to evidence records via `evidence_id`, `artifact_id`, and `checksum_sha256`.

## 7. Schema and Version Lifecycle
- SQLite schema version is managed via `PRAGMA user_version` and the `schema_migrations` table.
- Milestone 2.1 Prompt 1 establishes **Schema Version 1**.
- All schema migrations are executed within atomic transactions and forward-applied idempotently.
- SQLite is configured in **WAL (Write-Ahead Logging)** mode with `busy_timeout = 5000ms` for concurrent-read and safe write operations.

## 8. Failure and Degraded Behavior
The Experience Store implements **fail-safe graceful degradation** (Section 16):
- If the Experience database file is locked, missing, permission-denied, or corrupted, the core reviewer continues to function without interruption.
- Experience persistence failures log error messages and return degraded statuses rather than crashing the test session or assertion pipeline.
- `desktop-reviewer doctor` reports `WARN` rather than failing the overall test runner if the experience store is degraded.
- SQLite integrity is verified on demand via `PRAGMA integrity_check`.

## 9. Future Antigravity Integration Boundary
The schema and models support future agent-correlation identifiers (`agent_id`, `correlation_id`, `mission_id`), but no Antigravity hook bridge or internal coupling is implemented in Milestone 2.1 Prompt 1. The Experience Store functions completely offline and standalone.
