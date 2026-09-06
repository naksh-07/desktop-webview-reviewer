"""
Deterministic Pattern Detection Engine.
Architecture H / Milestone 2.1 Prompt 4.

Discovers explainable, reproducible patterns across accumulated observations:
- Recurring failure signatures
- Actions repeatedly requiring recovery
- Agent tool categories preceding failures
- Runtime conditions leading to verification UNKNOWN
- User corrections following failures

Every detected pattern is directly traceable to its underlying observation records.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from runtime.experience.learning.models import (
    DetectedPatternRecord,
    ObservationRecord,
    ObservationType,
    PatternType,
)
from runtime.experience.models import ExperienceScope

logger = logging.getLogger("desktop_webview.experience.learning.pattern_detector")


class DeterministicPatternDetector:
    """
    Deterministic pattern detector evaluating sets of ObservationRecords.
    Only declares patterns when empirical thresholds are satisfied.
    """

    MIN_PATTERN_OCCURRENCES = 2
    MIN_PATTERN_SESSIONS = 1

    @classmethod
    def detect_patterns(
        cls,
        observations: List[ObservationRecord],
        scope: ExperienceScope = ExperienceScope.PROJECT,
        project_id: Optional[str] = None,
    ) -> List[DetectedPatternRecord]:
        """
        Groups observations by signature and type to produce explainable DetectedPatternRecords.
        """
        if not observations:
            return []

        # Group by (observation_type, signature)
        clusters: Dict[Tuple[ObservationType, str], List[ObservationRecord]] = defaultdict(list)
        for obs in observations:
            clusters[(obs.observation_type, obs.signature)].append(obs)

        patterns: List[DetectedPatternRecord] = []

        for (obs_type, sig), obs_list in clusters.items():
            total_occurrences = sum(o.occurrence_count for o in obs_list)
            distinct_sessions: Set[str] = {o.session_id for o in obs_list if o.session_id}
            session_count = max(len(distinct_sessions), 1)

            # Enforce deterministic occurrence threshold
            if total_occurrences < cls.MIN_PATTERN_OCCURRENCES:
                continue

            # Determine corresponding pattern type
            pat_type = cls._map_observation_to_pattern_type(obs_type)

            # Sort observations chronologically
            sorted_obs = sorted(obs_list, key=lambda o: o.first_observed_ts)
            first_seen_at = sorted_obs[0].first_observed_at
            last_seen_at = sorted_obs[-1].last_observed_at
            first_seen_ts = sorted_obs[0].first_observed_ts
            last_seen_ts = sorted_obs[-1].last_observed_ts

            obs_refs = [o.observation_id for o in obs_list]
            sample_details = sorted_obs[-1].details

            summary = cls._generate_deterministic_summary(pat_type, sample_details, total_occurrences, session_count)

            # Compute pattern ID deterministically from type + signature
            pat_id_hash = hashlib.sha256(f"{pat_type.value}:{sig}".encode("utf-8")).hexdigest()[:12]
            pattern_id = f"pat_{pat_id_hash}"

            # Weighted confidence average
            conf = sum(o.confidence * o.occurrence_count for o in obs_list) / max(total_occurrences, 1)

            pattern = DetectedPatternRecord(
                pattern_id=pattern_id,
                pattern_type=pat_type,
                signature=sig,
                summary=summary,
                scope=scope,
                project_id=project_id,
                occurrence_count=total_occurrences,
                session_count=session_count,
                confidence=round(conf, 3),
                first_seen_at=first_seen_at,
                last_seen_at=last_seen_at,
                first_seen_ts=first_seen_ts,
                last_seen_ts=last_seen_ts,
                observation_refs=obs_refs,
                details={
                    "observation_type": obs_type.value,
                    "sample_details": sample_details,
                    "distinct_sessions": list(distinct_sessions),
                },
            )
            patterns.append(pattern)

        # Return deterministically sorted by occurrence_count desc, then pattern_id
        return sorted(patterns, key=lambda p: (-p.occurrence_count, p.pattern_id))

    @staticmethod
    def _map_observation_to_pattern_type(obs_type: ObservationType) -> PatternType:
        if obs_type == ObservationType.FAILURE_SIGNATURE:
            return PatternType.RECURRING_FAILURE
        elif obs_type == ObservationType.RECOVERY_PATTERN:
            return PatternType.REPEATED_RECOVERY_REQUIRED
        elif obs_type == ObservationType.TOOL_PRECEDING_FAILURE:
            return PatternType.AGENT_TOOL_FAILURE_CORRELATION
        elif obs_type == ObservationType.VERIFICATION_UNKNOWN:
            return PatternType.VERIFICATION_AMBIGUITY_CONDITION
        elif obs_type == ObservationType.USER_CORRECTION_FOLLOWING_FAILURE:
            return PatternType.USER_CORRECTION_SEQUENCE
        elif obs_type == ObservationType.TARGET_RESOLUTION_FAILURE:
            return PatternType.REPEATED_TARGET_RESOLUTION_FAILURE
        else:
            return PatternType.RECURRING_FAILURE

    @staticmethod
    def _generate_deterministic_summary(
        pat_type: PatternType,
        details: Dict[str, Any],
        occurrences: int,
        sessions: int,
    ) -> str:
        """
        Produces an explainable, fact-based summary without speculative model reasoning.
        """
        if pat_type == PatternType.RECURRING_FAILURE:
            cat = details.get("category", "UNKNOWN")
            return f"Repeated failure in category '{cat}' observed {occurrences} time(s) across {sessions} session(s)."

        elif pat_type == PatternType.REPEATED_RECOVERY_REQUIRED:
            action = details.get("recovery_action", "UNKNOWN")
            res = details.get("result", "UNKNOWN")
            return f"Repeated recovery action '{action}' resulting in '{res}' observed {occurrences} time(s)."

        elif pat_type == PatternType.AGENT_TOOL_FAILURE_CORRELATION:
            tool = details.get("tool_name", "UNKNOWN")
            cat = details.get("tool_category", "generic")
            return f"Agent tool '{tool}' (category: {cat}) repeatedly associated with failures ({occurrences} occurrences)."

        elif pat_type == PatternType.VERIFICATION_AMBIGUITY_CONDITION:
            err = details.get("error_category", "UNKNOWN")
            return f"Repeated verification ambiguity or UNKNOWN verdict under condition '{err}' ({occurrences} occurrences)."

        elif pat_type == PatternType.USER_CORRECTION_SEQUENCE:
            corr = details.get("correction_type", "UNKNOWN")
            return f"Repeated user correction of type '{corr}' following failure signature ({occurrences} occurrences)."

        elif pat_type == PatternType.REPEATED_TARGET_RESOLUTION_FAILURE:
            return f"Repeated target-resolution failure pattern observed {occurrences} time(s) across {sessions} session(s)."

        return f"Pattern of type '{pat_type.value}' observed {occurrences} time(s)."
