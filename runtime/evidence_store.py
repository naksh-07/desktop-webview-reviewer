"""
Safe, Sandboxed Evidence Storage Subsystem (Architecture H).
Provides content-addressed immutable artifact storage, atomic file persistence,
SHA-256 byte-level checksumming, and cryptographic tamper verification.
Enforces strict path isolation and traversal prevention according to docs/architecture/19_SECURITY_MODEL.md.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from runtime.evidence_models import (
    EvidenceArtifact,
    EvidenceManifest,
)
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.evidence_store")

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class EvidenceSecurityException(DesktopAutomationException):
    """Raised when an unsafe or traversing path is provided to EvidenceStore."""
    pass


class IntegrityVerificationException(DesktopAutomationException):
    """Raised when an evidence artifact or manifest fails cryptographic verification."""
    pass


EvidenceTamperException = IntegrityVerificationException


class EvidenceStore:
    """
    Manages physical storage, content hashing, and cryptographic integrity of evidence bundles.
    Layout:
      {base_dir}/
        session-{session_id}/
          action-{action_id}/
            manifest.json
            checksums.sha256
            artifacts/
              receipts/
              native/
              web/
              diffs/
              screenshots/
    """

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        if base_dir is None:
            base_dir = Path(os.getcwd()) / "evidence"
        self.base_dir = Path(base_dir).resolve()
        os.makedirs(self.base_dir, exist_ok=True)

    def _sanitize_id(self, identifier: str, id_type: str = "identifier") -> str:
        """Validates that session_id or action_id is safe and free from traversal tokens."""
        if not identifier or not isinstance(identifier, str):
            raise EvidenceSecurityException(f"Invalid {id_type}: must be a non-empty string.")
        
        # Strip potential common prefixes if passed repeatedly
        cleaned = identifier.strip()
        if not SAFE_ID_REGEX.match(cleaned) or ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            raise EvidenceSecurityException(
                f"Security violation: {id_type} '{identifier}' contains unsafe characters or directory traversal."
            )
        return cleaned

    def get_action_dir(self, session_id: str, action_id: str, create: bool = True) -> Path:
        """
        Resolves and validates the isolated directory for a specific action transaction.
        Enforces sandboxing under self.base_dir.
        """
        s_id = self._sanitize_id(session_id, "session_id")
        a_id = self._sanitize_id(action_id, "action_id")

        action_path = (self.base_dir / f"session-{s_id}" / f"action-{a_id}").resolve()

        # Sandboxing check: ensure resolved path is strictly within base_dir
        try:
            action_path.relative_to(self.base_dir)
        except ValueError:
            raise EvidenceSecurityException(f"Path traversal detected: {action_path} escapes {self.base_dir}")

        if create:
            os.makedirs(action_path, exist_ok=True)

        return action_path

    def _validate_relative_path(self, relative_path: str) -> Path:
        """Validates that a relative artifact path does not escape the parent directory."""
        if os.path.isabs(relative_path) or relative_path.startswith(("/", "\\")) or ":" in relative_path:
            raise EvidenceSecurityException(
                f"Unsafe artifact path '{relative_path}': absolute paths or drive letters are prohibited."
            )
        clean_rel = relative_path.replace("\\", "/")
        parts = clean_rel.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise EvidenceSecurityException(
                f"Unsafe artifact path '{relative_path}': path traversal or dot-segments are prohibited."
            )
        return Path(clean_rel)

    def store_bytes(
        self,
        session_id: str,
        action_id: str,
        relative_path: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvidenceArtifact:
        """
        Atomically writes arbitrary bytes to an artifact path, computing exact SHA-256.
        """
        action_dir = self.get_action_dir(session_id, action_id, create=True)
        rel_p = self._validate_relative_path(relative_path)
        dest_path = (action_dir / rel_p).resolve()

        # Enforce sandbox
        try:
            dest_path.relative_to(action_dir)
        except ValueError:
            raise EvidenceSecurityException(f"Artifact path {dest_path} escapes action dir {action_dir}")

        os.makedirs(dest_path.parent, exist_ok=True)

        # Compute SHA-256
        sha256_hash = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)

        # Atomic write via temporary file in the same directory
        tmp_name = f".tmp_{uuid.uuid4().hex}_{dest_path.name}"
        tmp_path = dest_path.parent / tmp_name

        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, dest_path)
        except Exception:
            if tmp_path.exists():
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

        artifact = EvidenceArtifact(
            artifact_id=f"art_{uuid.uuid4().hex[:12]}",
            filename=dest_path.name,
            mime_type=mime_type,
            sha256=sha256_hash,
            size_bytes=size_bytes,
            created_at=os.path.getmtime(dest_path),
            relative_path=str(rel_p).replace("\\", "/"),
            metadata=metadata or {},
        )
        return artifact

    def store_json(
        self,
        session_id: str,
        action_id: str,
        relative_path: str,
        obj: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvidenceArtifact:
        """Serializes and writes an object as formatted UTF-8 JSON."""
        data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
        return self.store_bytes(
            session_id=session_id,
            action_id=action_id,
            relative_path=relative_path,
            data=data,
            mime_type="application/json",
            metadata=metadata,
        )

    def store_manifest(self, manifest: EvidenceManifest) -> Tuple[Path, str]:
        """
        Saves the authoritative manifest.json and companion checksums.sha256 file.
        Returns the absolute Path to manifest.json and the manifest hash.
        """
        action_dir = self.get_action_dir(manifest.session_id, manifest.action_id, create=True)
        manifest_path = action_dir / "manifest.json"
        checksums_path = action_dir / "checksums.sha256"

        manifest_dict = manifest.to_dict(include_hash=True)
        manifest_bytes = json.dumps(manifest_dict, indent=2, sort_keys=True).encode("utf-8")

        # Atomic write of manifest.json
        tmp_manifest = action_dir / f".tmp_{uuid.uuid4().hex}_manifest.json"
        with open(tmp_manifest, "wb") as f:
            f.write(manifest_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_manifest, manifest_path)

        # Build checksums.sha256
        checksum_lines = []
        for art in manifest.artifacts:
            checksum_lines.append(f"{art.sha256}  {art.relative_path}")
        manifest_hash = manifest.manifest_hash or manifest.compute_manifest_hash()
        checksum_lines.append(f"{manifest_hash}  manifest.json")
        checksum_bytes = ("\n".join(checksum_lines) + "\n").encode("utf-8")

        tmp_checksum = action_dir / f".tmp_{uuid.uuid4().hex}_checksums.sha256"
        with open(tmp_checksum, "wb") as f:
            f.write(checksum_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_checksum, checksums_path)

        return manifest_path, manifest_hash

    def load_manifest(self, manifest_path_or_dir: Union[str, Path]) -> EvidenceManifest:
        """Loads and parses an EvidenceManifest from a file or directory path."""
        p = Path(manifest_path_or_dir).resolve()
        if p.is_dir():
            p = p / "manifest.json"

        if not p.exists():
            raise FileNotFoundError(f"Manifest not found at {p}")

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        return EvidenceManifest.from_dict(data)

    def load_artifact_bytes(self, session_id: str, action_id: str, relative_path: str) -> bytes:
        """Loads raw bytes for a stored artifact after validating path safety."""
        action_dir = self.get_action_dir(session_id, action_id, create=False)
        rel_p = self._validate_relative_path(relative_path)
        art_path = (action_dir / rel_p).resolve()

        try:
            art_path.relative_to(action_dir)
        except ValueError:
            raise EvidenceSecurityException(f"Access denied: {art_path} escapes action dir {action_dir}")

        if not art_path.exists():
            raise FileNotFoundError(f"Artifact {relative_path} not found in {action_dir}")

        with open(art_path, "rb") as f:
            return f.read()

    def verify_manifest_integrity(
        self,
        manifest_or_path: Union[EvidenceManifest, str, Path],
    ) -> Tuple[bool, List[str]]:
        """
        Cryptographically verifies an evidence bundle against its manifest.
        Checks:
        1. Canonical manifest hash self-verification.
        2. Presence of all referenced artifacts on disk.
        3. Exact SHA-256 hash match for each artifact byte stream.
        4. Artifact file size consistency.
        5. Duplicate artifact IDs.
        6. Integrity of checksums.sha256 if present.

        Returns (is_valid, violations_list). Fails closed.
        """
        violations: List[str] = []

        if isinstance(manifest_or_path, EvidenceManifest):
            manifest = manifest_or_path
            action_dir = self.get_action_dir(manifest.session_id, manifest.action_id, create=False)
        else:
            p = Path(manifest_or_path).resolve()
            if p.is_dir():
                manifest_file = p / "manifest.json"
                action_dir = p
            else:
                manifest_file = p
                action_dir = p.parent

            if not manifest_file.exists():
                return False, [f"Manifest file missing: {manifest_file}"]

            try:
                manifest = self.load_manifest(manifest_file)
            except Exception as e:
                return False, [f"Corrupted manifest JSON: {e}"]

        # 1. Verify Manifest Hash
        recomputed_hash = manifest.compute_manifest_hash()
        if manifest.manifest_hash and manifest.manifest_hash != recomputed_hash:
            violations.append(
                f"Manifest tampering detected: stored hash={manifest.manifest_hash}, computed hash={recomputed_hash}"
            )

        # 2. Check for duplicate artifact IDs or duplicate filenames
        seen_art_ids = set()
        seen_paths = set()
        for art in manifest.artifacts:
            if art.artifact_id in seen_art_ids:
                violations.append(f"Duplicate artifact ID detected: '{art.artifact_id}'")
            seen_art_ids.add(art.artifact_id)

            if art.relative_path in seen_paths:
                violations.append(f"Duplicate relative path detected: '{art.relative_path}'")
            seen_paths.add(art.relative_path)

        # 3. Verify Artifact Files on Disk
        for art in manifest.artifacts:
            try:
                rel_p = self._validate_relative_path(art.relative_path)
            except EvidenceSecurityException as e:
                violations.append(f"Security violation in artifact path '{art.relative_path}': {e}")
                continue

            art_path = (action_dir / rel_p).resolve()
            try:
                art_path.relative_to(action_dir)
            except ValueError:
                violations.append(f"Path traversal detected in artifact: {art_path}")
                continue

            if not art_path.exists():
                violations.append(f"Missing artifact file on disk: '{art.relative_path}' ({art_path})")
                continue

            try:
                with open(art_path, "rb") as f:
                    content = f.read()
                actual_sha = hashlib.sha256(content).hexdigest()
                actual_size = len(content)

                if actual_sha != art.sha256:
                    violations.append(
                        f"Artifact tampering detected for '{art.relative_path}': expected sha256={art.sha256}, actual sha256={actual_sha}"
                    )

                if art.size_bytes and actual_size != art.size_bytes:
                    violations.append(
                        f"Artifact size mismatch for '{art.relative_path}': expected {art.size_bytes} bytes, got {actual_size} bytes"
                    )
            except Exception as e:
                violations.append(f"Failed to read artifact '{art.relative_path}': {e}")

        # 4. Verify checksums.sha256 file if present
        checksums_path = action_dir / "checksums.sha256"
        if checksums_path.exists():
            try:
                with open(checksums_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = re.split(r"\s+", line, maxsplit=1)
                    if len(parts) == 2:
                        chk_hash, chk_file = parts
                        if chk_file == "manifest.json":
                            if manifest.manifest_hash and chk_hash != manifest.manifest_hash:
                                violations.append(
                                    f"Checksums file manifest hash mismatch: {chk_hash} != {manifest.manifest_hash}"
                                )
                        else:
                            matched_art = next((a for a in manifest.artifacts if a.relative_path == chk_file or a.filename == chk_file), None)
                            if matched_art and matched_art.sha256 != chk_hash:
                                violations.append(
                                    f"Checksums file mismatch for '{chk_file}': {chk_hash} != {matched_art.sha256}"
                                )
            except Exception as e:
                violations.append(f"Failed to verify checksums.sha256: {e}")

        is_valid = len(violations) == 0
        return is_valid, violations

    def assert_manifest_integrity(self, manifest_or_path: Union[EvidenceManifest, str, Path]) -> None:
        """
        Asserts that the evidence bundle is mathematically and cryptographically untampered.
        Raises IntegrityVerificationException if any violation is found.
        """
        is_valid, violations = self.verify_manifest_integrity(manifest_or_path)
        if not is_valid:
            raise IntegrityVerificationException(
                f"Cryptographic evidence integrity verification failed with {len(violations)} violations: "
                + "; ".join(violations)
            )
