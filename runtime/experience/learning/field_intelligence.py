"""
Field Intelligence Query & Aggregate Reporting Engine.
Architecture H / Milestone 2.1 Prompt 4.

Provides 12 descriptive, non-causal aggregate queries over accumulated experience:
1. Top recurring failure signatures
2. Failure recurrence by action type
3. Recovery success by strategy/category
4. Verification outcome distribution over time
5. Agent tool categories associated with failures
6. User corrections associated with recurring failures
7. Most frequent improvement candidates
8. Candidate validation status
9. Durable knowledge due for review
10. Stale/superseded knowledge
11. Experience volume by project/scope
12. Newly emerging patterns

Adheres strictly to descriptive terminology ('associated with', not 'caused by').
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from runtime.experience.learning.models import FieldIntelligenceReport

logger = logging.getLogger("desktop_webview.experience.learning.field_intelligence")


class FieldIntelligenceEngine:
    """
    Executes historical aggregate queries against SQLite Experience Store.
    """

    def __init__(self, conn_provider: Any):
        """
        conn_provider: callable returning an active sqlite3.Connection,
        an ExperienceStore instance, or a sqlite3.Connection.
        """
        if hasattr(conn_provider, "_get_connection"):
            self._conn_provider = conn_provider._get_connection
        else:
            self._conn_provider = conn_provider

    def generate_comprehensive_report(self, project_id: Optional[str] = None) -> FieldIntelligenceReport:
        """Alias for generate_full_report with optional project filter."""
        return self.generate_full_report()

    def _get_conn(self) -> sqlite3.Connection:
        if callable(self._conn_provider):
            return cast(sqlite3.Connection, self._conn_provider())
        return cast(sqlite3.Connection, self._conn_provider)

    # 1. Top recurring failure signatures
    def query_top_recurring_failures(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT signature, category, COUNT(*) as count, MAX(iso_timestamp) as latest_timestamp,
                   COUNT(DISTINCT session_id) as session_count
            FROM normalized_failures
            GROUP BY signature, category
            ORDER BY count DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "signature": row["signature"],
                "category": row["category"],
                "occurrence_count": row["count"],
                "session_count": row["session_count"],
                "latest_timestamp": row["latest_timestamp"],
                "description": f"Failure signature in category '{row['category']}' observed {row['count']} time(s)",
            }
            for row in rows
        ]

    # 2. Failure recurrence by action type
    def query_failures_by_action_type(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        # Query action_references joined with normalized_failures on action_id or session_id
        cursor.execute(
            """
            SELECT a.action_type, COUNT(f.failure_id) as failure_count
            FROM action_references a
            JOIN normalized_failures f ON a.action_id = f.action_id
            GROUP BY a.action_type
            ORDER BY failure_count DESC;
            """
        )
        rows = cursor.fetchall()
        if not rows:
            # Fallback: scan safe_context_json inside normalized_failures
            cursor.execute("SELECT safe_context_json FROM normalized_failures;")
            counts: Dict[str, int] = {}
            for r in cursor.fetchall():
                if r[0]:
                    try:
                        import json
                        ctx = json.loads(r[0])
                        act = ctx.get("action_type", "UNKNOWN")
                        counts[act] = counts.get(act, 0) + 1
                    except Exception:
                        pass
            return [
                {
                    "action_type": k,
                    "associated_failure_count": v,
                    "description": f"Action type '{k}' associated with {v} failure receipt(s)",
                }
                for k, v in sorted(counts.items(), key=lambda x: -x[1])
            ]

        return [
            {
                "action_type": row["action_type"],
                "associated_failure_count": row["failure_count"],
                "description": f"Action type '{row['action_type']}' associated with {row['failure_count']} failure receipt(s)",
            }
            for row in rows
        ]

    # 3. Recovery success by strategy/category
    def query_recovery_success_by_strategy(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT failure_category, recovery_action,
                   COUNT(*) as total_attempts,
                   SUM(CASE WHEN result = 'SUCCESS' THEN 1 ELSE 0 END) as successful_attempts,
                   SUM(CASE WHEN result = 'FAILED' THEN 1 ELSE 0 END) as failed_attempts,
                   AVG(duration_ms) as mean_duration_ms
            FROM recovery_attempts
            GROUP BY failure_category, recovery_action
            ORDER BY total_attempts DESC;
            """
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            tot = r["total_attempts"]
            succ = r["successful_attempts"] or 0
            rate = round((succ / tot) if tot > 0 else 0.0, 3)
            results.append({
                "failure_category": r["failure_category"],
                "recovery_action": r["recovery_action"],
                "total_attempts": tot,
                "successful_attempts": succ,
                "failed_attempts": r["failed_attempts"] or 0,
                "success_rate": rate,
                "mean_duration_ms": round(r["mean_duration_ms"] or 0.0, 2),
                "description": f"Strategy '{r['recovery_action']}' for '{r['failure_category']}': {rate:.1%} success across {tot} attempt(s)",
            })
        return results

    # 4. Verification outcome distribution over time
    def query_verification_distribution(self) -> Dict[str, Any]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT verdict, COUNT(*) as count
            FROM experience_outcomes
            GROUP BY verdict;
            """
        )
        rows = cursor.fetchall()
        counts = {r["verdict"]: r["count"] for r in rows}
        tot = sum(counts.values())
        return {
            "total_outcomes": tot,
            "pass_count": counts.get("PASS", 0),
            "fail_count": counts.get("FAIL", 0),
            "unverified_count": counts.get("UNVERIFIED", 0),
            "pass_rate": round((counts.get("PASS", 0) / tot) if tot > 0 else 0.0, 3),
            "fail_rate": round((counts.get("FAIL", 0) / tot) if tot > 0 else 0.0, 3),
            "unverified_rate": round((counts.get("UNVERIFIED", 0) / tot) if tot > 0 else 0.0, 3),
        }

    # 5. Agent tool categories associated with failures
    def query_agent_tool_categories_associated_with_failures(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT tool_category, COUNT(*) as failure_association_count
            FROM agent_tool_calls
            WHERE success = 0
            GROUP BY tool_category
            ORDER BY failure_association_count DESC;
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "tool_category": r["tool_category"],
                "associated_failure_count": r["failure_association_count"],
                "description": f"Agent tool category '{r['tool_category']}' associated with {r['failure_association_count']} uncompleted call(s)",
            }
            for r in rows
        ]

    # 6. User corrections associated with recurring failures
    def query_user_corrections_associated_with_failures(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT correction_type, COUNT(*) as count,
                   COUNT(DISTINCT related_dwr_session_id) as session_count
            FROM agent_corrections
            GROUP BY correction_type
            ORDER BY count DESC;
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "correction_type": r["correction_type"],
                "count": r["count"],
                "session_count": r["session_count"],
                "description": f"User correction type '{r['correction_type']}' observed {r['count']} time(s)",
            }
            for r in rows
        ]

    # 7. Most frequent improvement candidates
    def query_frequent_candidates(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT candidate_id, category, affected_subsystem, status, risk_level,
                   evidence_count, session_count, confidence, rationale_summary
            FROM improvement_candidates
            ORDER BY evidence_count DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "candidate_id": r["candidate_id"],
                "category": r["category"],
                "affected_subsystem": r["affected_subsystem"],
                "status": r["status"],
                "risk_level": r["risk_level"],
                "evidence_count": r["evidence_count"],
                "session_count": r["session_count"],
                "confidence": r["confidence"],
                "rationale_summary": r["rationale_summary"],
            }
            for r in rows
        ]

    # 8. Candidate validation status
    def query_candidate_validation_status(self) -> Dict[str, int]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT status, COUNT(*) as count
            FROM improvement_candidates
            GROUP BY status;
            """
        )
        rows = cursor.fetchall()
        return {r["status"]: r["count"] for r in rows}

    # 9. Durable knowledge due for review
    def query_durable_knowledge_due_for_review(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            SELECT knowledge_id, normalized_statement, scope, status, review_due_at, contradiction_count
            FROM durable_knowledge
            WHERE status = 'REVIEW_DUE' OR (review_due_at IS NOT NULL AND review_due_at <= ?)
            ORDER BY review_due_at ASC;
            """,
            (now_iso,),
        )
        rows = cursor.fetchall()
        return [
            {
                "knowledge_id": r["knowledge_id"],
                "normalized_statement": r["normalized_statement"],
                "scope": r["scope"],
                "status": r["status"],
                "review_due_at": r["review_due_at"],
                "contradiction_count": r["contradiction_count"],
                "description": f"Knowledge '{r['knowledge_id']}' is due for human review since {r['review_due_at']}",
            }
            for r in rows
        ]

    # 10. Stale / superseded knowledge
    def query_stale_or_superseded_knowledge(self) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT knowledge_id, normalized_statement, status, updated_at, superseded_by, contradiction_count
            FROM durable_knowledge
            WHERE status IN ('STALE', 'SUPERSEDED', 'RETIRED')
            ORDER BY updated_at DESC;
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "knowledge_id": r["knowledge_id"],
                "normalized_statement": r["normalized_statement"],
                "status": r["status"],
                "updated_at": r["updated_at"],
                "superseded_by": r["superseded_by"],
                "contradiction_count": r["contradiction_count"],
            }
            for r in rows
        ]

    # 11. Experience volume by project / scope
    def query_experience_volume_by_scope(self) -> Dict[str, Any]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT scope, COUNT(*) as count
            FROM review_sessions
            GROUP BY scope;
            """
        )
        rows = cursor.fetchall()
        scope_counts = {r["scope"]: r["count"] for r in rows}

        cursor.execute("SELECT COUNT(DISTINCT project_id) FROM review_sessions WHERE project_id IS NOT NULL;")
        proj_count = cursor.fetchone()[0]

        return {
            "sessions_by_scope": scope_counts,
            "total_projects": proj_count,
        }

    # 12. Newly emerging patterns
    def query_emerging_patterns(self, limit: int = 5) -> List[Dict[str, Any]]:
        cursor = self._get_conn().cursor()
        cursor.execute(
            """
            SELECT pattern_id, pattern_type, summary, occurrence_count, session_count, first_seen_at
            FROM detected_patterns
            ORDER BY first_seen_ts DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "pattern_id": r["pattern_id"],
                "pattern_type": r["pattern_type"],
                "summary": r["summary"],
                "occurrence_count": r["occurrence_count"],
                "session_count": r["session_count"],
                "first_seen_at": r["first_seen_at"],
            }
            for r in rows
        ]

    def generate_full_report(self) -> FieldIntelligenceReport:
        """
        Compiles all 12 queries into a consolidated FieldIntelligenceReport.
        """
        return FieldIntelligenceReport(
            top_recurring_failures=self.query_top_recurring_failures(),
            failures_by_action_type=self.query_failures_by_action_type(),
            recovery_success_by_strategy=self.query_recovery_success_by_strategy(),
            verification_distribution=self.query_verification_distribution(),
            agent_tool_failures=self.query_agent_tool_categories_associated_with_failures(),
            user_corrections=self.query_user_corrections_associated_with_failures(),
            frequent_candidates=self.query_frequent_candidates(),
            candidate_validation_status=self.query_candidate_validation_status(),
            knowledge_due_for_review=self.query_durable_knowledge_due_for_review(),
            stale_or_superseded_knowledge=self.query_stale_or_superseded_knowledge(),
            experience_volume_by_scope=self.query_experience_volume_by_scope(),
            emerging_patterns=self.query_emerging_patterns(),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
