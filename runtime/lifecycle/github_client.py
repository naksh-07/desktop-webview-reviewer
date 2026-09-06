"""
GitHub Releases Integration Client for Desktop WebView Reviewer.

Discovers stable tagged releases from GitHub API without depending on external tools.
Fails softly when offline or rate-limited: never corrupts state or crashes runtime.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import List, Optional
from packaging.version import InvalidVersion, Version

from runtime.lifecycle.models import UpdateCandidate

logger = logging.getLogger("desktop_webview.lifecycle.github")

DEFAULT_REPO: str = "naksh-07/desktop-webview-reviewer"
API_TIMEOUT_SEC: float = 6.0


class GitHubReleasesClient:
    """Client for querying release distribution metadata from GitHub."""

    def __init__(self, repo: Optional[str] = None):
        self.repo = repo or os.environ.get("DESKTOP_REVIEWER_GITHUB_REPO", DEFAULT_REPO)
        self.api_url = f"https://api.github.com/repos/{self.repo}/releases"

    def fetch_releases(self) -> List[UpdateCandidate]:
        """
        Fetches all tagged releases.
        Returns a sorted list of UpdateCandidate objects (newest semver first).
        If offline, rate-limited, or network fails, returns an empty list.
        """
        # Test fixture / mock override support
        mock_file = os.environ.get("DESKTOP_REVIEWER_MOCK_RELEASES_FILE")
        if mock_file and os.path.isfile(mock_file):
            try:
                with open(mock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._parse_releases_json(data)
            except Exception as e:
                logger.warning("Failed to parse mock releases file: %s", e)
                return []

        headers = {
            "User-Agent": "Desktop-WebView-Reviewer-Updater",
            "Accept": "application/vnd.github.v3+json",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"

        req = urllib.request.Request(self.api_url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT_SEC) as resp:
                if resp.status != 200:
                    logger.warning("GitHub Releases API returned status %d", resp.status)
                    return []
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return self._parse_releases_json(data)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            logger.info("GitHub Releases check unavailable: %s", err)
            return []
        except Exception as exc:
            logger.warning("Unexpected error during GitHub Releases check: %s", exc)
            return []

    def _parse_releases_json(self, data: List[dict]) -> List[UpdateCandidate]:
        """Parses and filters raw GitHub release entries to valid semver candidates."""
        candidates: List[UpdateCandidate] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            # Do not consider drafts
            if item.get("draft", False):
                continue

            tag_name = item.get("tag_name", "").strip()
            # Clean tag name to semver (e.g. v2.0.1 -> 2.0.1)
            raw_ver = tag_name.lstrip("v")
            try:
                parsed = Version(raw_ver)
            except InvalidVersion:
                # Ignore non-semver tags
                continue

            # Extract wheel / tarball asset download URLs if present
            download_url = None
            assets = item.get("assets", [])
            for asset in assets:
                name = asset.get("name", "")
                if name.endswith(".whl"):
                    download_url = asset.get("browser_download_url")
                    break

            candidates.append(
                UpdateCandidate(
                    version=str(parsed),
                    tag_name=tag_name,
                    release_name=item.get("name") or tag_name,
                    release_notes=item.get("body") or "",
                    published_at=item.get("published_at") or "",
                    prerelease=item.get("prerelease", False),
                    download_url=download_url,
                    tarball_url=item.get("tarball_url"),
                )
            )

        # Sort candidates descending by semver
        candidates.sort(key=lambda c: Version(c.version), reverse=True)
        return candidates

    def get_latest_stable_release(self) -> Optional[UpdateCandidate]:
        """Returns the newest stable (non-prerelease) release candidate, or None."""
        releases = self.fetch_releases()
        for rel in releases:
            if not rel.prerelease:
                return rel
        return None

    def get_release_by_version(self, target_version: str) -> Optional[UpdateCandidate]:
        """Returns candidate matching target_version if available."""
        clean_target = target_version.lstrip("v").strip()
        for rel in self.fetch_releases():
            if rel.version == clean_target or rel.tag_name == target_version:
                return rel
        return None
