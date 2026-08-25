"""
Universal target discovery, endpoint querying, and runtime process correlation.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import List, Optional, Set, Tuple

from .models import Target, TargetCriteria
from .window_forensics import WindowForensicsEngine

logger = logging.getLogger("desktop_webview.discovery")


class TargetDiscovery:
    """Discovers, queries, and correlates inspectable targets from a remote debugging endpoint."""

    @staticmethod
    def query_targets(host: str = "127.0.0.1", port: int = 9222, engine: str = "generic") -> List[Target]:
        """Queries the /json/list endpoint once and returns all parsed Targets."""
        url = f"http://{host}:{port}/json/list"
        targets: List[Target] = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DesktopWebviewReviewer/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response.status == 200:
                    raw_data = response.read().decode("utf-8")
                    data = json.loads(raw_data)
                    if isinstance(data, list):
                        for item in data:
                            target_id = item.get("id", "")
                            target_type = item.get("type", "page")
                            title = item.get("title", "")
                            target_url = item.get("url", "")
                            ws_url = item.get("webSocketDebuggerUrl")
                            targets.append(Target(
                                id=target_id,
                                type=target_type,
                                title=title,
                                url=target_url,
                                engine=engine,
                                debug_endpoint=f"http://{host}:{port}",
                                websocket_endpoint=ws_url,
                                metadata=item
                            ))
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError, json.JSONDecodeError) as e:
            logger.debug(f"Target query to {url} failed: {e}")
        return targets

    @classmethod
    def poll_for_targets(
        cls,
        host: str = "127.0.0.1",
        port: int = 9222,
        engine: str = "generic",
        timeout: float = 15.0,
        interval: float = 0.5
    ) -> List[Target]:
        """Polls the endpoint until at least one target appears or timeout expires."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            targets = cls.query_targets(host=host, port=port, engine=engine)
            if targets:
                return targets
            time.sleep(interval)
        return []

    @staticmethod
    def verify_port_ownership(port: int, expected_pids: Set[int]) -> Tuple[bool, Optional[int], str]:
        """
        Verifies that the process listening on `port` belongs to the expected process tree.
        """
        return WindowForensicsEngine.verify_port_listening_process(port, expected_pids)

    IGNORED_URL_PREFIXES = (
        "devtools://",
        "chrome-devtools://",
        "chrome://",
        "edge://",
        "chrome-extension://",
    )

    IGNORED_TYPES = (
        "service_worker",
        "background_page",
        "worker",
        "node",
        "other",
    )

    @classmethod
    def is_application_target(cls, target: Target) -> bool:
        """Determines if a target is an application-owned page/webview surface."""
        if target.type and target.type.lower() in cls.IGNORED_TYPES:
            return False

        url_lower = target.url.lower()
        if any(url_lower.startswith(prefix) for prefix in cls.IGNORED_URL_PREFIXES):
            return False

        # Reject pure empty about:blank without a descriptive title
        if target.url in ("about:blank", "") and not target.title.strip():
            return False

        return True

    @classmethod
    def rank_target(cls, target: Target, criteria: Optional[TargetCriteria] = None) -> int:
        """Computes a heuristic ranking score for a target and records filter reasons."""
        score = 0
        is_app = True
        filter_reason = None

        # Type checks
        if target.type and target.type.lower() in cls.IGNORED_TYPES:
            score -= 100
            is_app = False
            filter_reason = f"Ignored type: '{target.type}'"
        elif target.type in ("page", "webview", "app"):
            score += 20

        # Protocol check
        url_lower = target.url.lower()
        if any(url_lower.startswith(prefix) for prefix in cls.IGNORED_URL_PREFIXES):
            score -= 200
            is_app = False
            filter_reason = f"Ignored URL prefix: '{target.url[:30]}...'"

        # Pure empty about:blank check
        if target.url in ("about:blank", "") and not (target.title and target.title.strip()):
            score -= 50
            if is_app:
                filter_reason = "Empty about:blank target"

        # Meaningful content bonuses
        if target.title and target.title.strip() and target.title != "about:blank":
            score += 25

        if url_lower.startswith(("file://", "http://", "https://", "app://", "tauri://", "wails://", "custom://")):
            score += 25

        if criteria:
            if criteria.engine and target.engine == criteria.engine:
                score += 10
            if criteria.title_pattern and criteria.title_pattern.lower() in target.title.lower():
                score += 100
            if criteria.url_pattern and criteria.url_pattern.lower() in target.url.lower():
                score += 100
            if criteria.custom_filter and criteria.custom_filter(target):
                score += 150

        target.rank_score = score
        target.is_application = is_app
        target.filter_reason = filter_reason
        return score

    @classmethod
    def filter_targets(cls, targets: List[Target], criteria: Optional[TargetCriteria] = None) -> List[Target]:
        """Filters a list of targets against criteria and sorts by ranking priority."""
        if not targets:
            return []

        for t in targets:
            cls.rank_target(t, criteria)

        candidates: List[Target] = []
        for t in targets:
            if criteria:
                if criteria.target_type and t.type != criteria.target_type:
                    continue
                if criteria.title_pattern and criteria.title_pattern.lower() not in t.title.lower():
                    continue
                if criteria.url_pattern and criteria.url_pattern.lower() not in t.url.lower():
                    continue
                if criteria.engine and t.engine != criteria.engine:
                    continue
                if criteria.custom_filter and not criteria.custom_filter(t):
                    continue
            candidates.append(t)

        # Sort candidates by ranking score descending
        candidates.sort(key=lambda t: t.rank_score, reverse=True)
        return candidates

    @classmethod
    def format_ranking_diagnostics(cls, targets: List[Target], selected_target: Optional[Target] = None) -> str:
        """Formats clear human-readable diagnostic ranking table."""
        lines = ["Target ranking diagnostics:"]
        sorted_targets = sorted(targets, key=lambda t: t.rank_score, reverse=True)
        for i, t in enumerate(sorted_targets, start=1):
            is_selected = selected_target and t.id == selected_target.id
            tag = " [SELECTED]" if is_selected else ""
            status = f"score {t.rank_score}" if t.is_application else f"filtered ({t.filter_reason or 'non-app'})"
            title = t.title or t.url or f"Target {t.id[:8]}"
            lines.append(f"  {i}. {title:<30} {status:<35}{tag}")
        return "\n".join(lines)

    @classmethod
    def select_target(
        cls,
        targets: List[Target],
        criteria: Optional[TargetCriteria] = None
    ) -> Optional[Target]:
        """Selects the highest-ranked target matching criteria with diagnostic logging."""
        if not targets:
            logger.warning("Target selection called with empty targets list.")
            return None

        # Ensure all targets are scored
        for t in targets:
            cls.rank_target(t, criteria)

        # First attempt filtered ranking
        ranked = cls.filter_targets(targets, criteria)
        if ranked:
            selected = ranked[criteria.index] if (criteria and 0 <= criteria.index < len(ranked)) else ranked[0]
            logger.info(
                f"Selected target: ID='{selected.id}', Title='{selected.title}', URL='{selected.url}', "
                f"Type='{selected.type}' (Score={selected.rank_score})"
            )
            return selected

        # Fallback: find any application-owned target
        app_targets = [t for t in targets if t.is_application]
        if app_targets:
            app_targets.sort(key=lambda t: t.rank_score, reverse=True)
            selected = app_targets[0]
            logger.warning(
                f"Criteria filter did not match; fell back to best application target: "
                f"ID='{selected.id}', Title='{selected.title}'"
            )
            return selected

        # Ultimate fallback
        logger.warning("No ideal application target found; returning first available target.")
        return targets[0]
