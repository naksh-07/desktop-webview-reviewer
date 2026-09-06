#!/usr/bin/env python3
"""
CLI Governance & Field Intelligence Operations.
Architecture H / Milestone 2.1 Prompt 4.

Provides safe programmatic/CLI governance surfaces:
- list: List improvement candidates
- inspect: Inspect candidate details and evidence gate evaluations
- validate: Run deterministic validation gates on a candidate
- approve: Human approval gate to promote candidate to durable knowledge
- reject: Reject a candidate with explicit rationale
- decay: Evaluate knowledge decay, staleness, and review deadlines
- field-intel: Display descriptive aggregate field intelligence
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.candidate_generator import ImprovementCandidateGenerator
from runtime.experience.learning.decay import KnowledgeDecayEngine
from runtime.experience.learning.field_intelligence import FieldIntelligenceEngine
from runtime.experience.learning.governance import GovernanceEngine
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    GovernanceDecision,
    KnowledgeStatus,
)
from runtime.experience.learning.safety_gate import LearningSafetyGate
from runtime.experience.models import ExperienceScope
from runtime.experience.store import ExperienceStore

logger = logging.getLogger("desktop_webview.learning_cli")


def cmd_list(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Lists improvement candidates filtered by status or scope."""
    status_filter = None
    if args.status:
        try:
            status_filter = CandidateStatus(args.status.upper())
        except ValueError:
            print(f"Error: Invalid status '{args.status}'. Options: {[s.value for s in CandidateStatus]}")
            return 1

    scope_filter = None
    if args.scope:
        try:
            scope_filter = ExperienceScope(args.scope.lower())
        except ValueError:
            print(f"Error: Invalid scope '{args.scope}'. Options: {[s.value for s in ExperienceScope]}")
            return 1

    candidates = store.get_improvement_candidates(
        status=status_filter,
        scope=scope_filter,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps([c.to_dict() for c in candidates], indent=2))
        return 0

    print("=" * 80)
    print(f"  Desktop WebView Reviewer — Improvement Candidates ({len(candidates)} found)")
    print("=" * 80)
    if not candidates:
        print("  No candidates found matching the specified filters.")
        print("-" * 80)
        return 0

    header = f"{'ID':<14} {'STATUS':<20} {'SCOPE':<9} {'EVID':<5} {'SESS':<5} {'CONF':<6} {'CATEGORY'}"
    print(header)
    print("-" * 80)
    for c in candidates:
        cid_short = c.candidate_id[:12] + ".." if len(c.candidate_id) > 14 else c.candidate_id
        line = (
            f"{cid_short:<14} {c.status.value:<20} {c.scope.value:<9} "
            f"{c.evidence_count:<5} {c.session_count:<5} {c.confidence:<6.2f} {c.category.value}"
        )
        print(line)
        print(f"   Rationale: {c.rationale_summary}")
    print("-" * 80)
    return 0


def cmd_inspect(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Displays detailed candidate record and gate evaluation."""
    candidate = store.get_improvement_candidate(args.candidate_id)
    if not candidate:
        print(f"Error: Candidate '{args.candidate_id}' not found.")
        return 1

    passes_safety, gate_results = LearningSafetyGate.evaluate_candidate_safety(
        candidate=candidate,
        contradiction_count=0,
        is_human_approved=(candidate.status in (CandidateStatus.HUMAN_APPROVED, CandidateStatus.DURABLE)),
    )

    if args.json:
        data = candidate.to_dict()
        data["safety_gate_evaluation"] = {
            "passes_all_gates": passes_safety,
            "gates": {k: v.to_dict() for k, v in gate_results.items()},
        }
        print(json.dumps(data, indent=2))
        return 0

    print("=" * 80)
    print(f"  Candidate Details: {candidate.candidate_id}")
    print("=" * 80)
    print(f"Category:            {candidate.category.value}")
    print(f"Status:              {candidate.status.value}")
    print(f"Scope:               {candidate.scope.value}")
    print(f"Affected Subsystem:  {candidate.affected_subsystem}")
    print(f"Risk Level:          {candidate.risk_level.value}")
    print(f"Confidence:          {candidate.confidence:.2f}")
    print(f"Evidence Count:      {candidate.evidence_count}")
    print(f"Session Count:       {candidate.session_count}")
    print(f"First Seen:          {candidate.first_seen_at}")
    print(f"Last Seen:           {candidate.last_seen_at}")
    print(f"Pattern Reference:   {candidate.pattern_id}")
    obs_refs = candidate.metadata.get("observation_refs", [])
    print(f"Observations ({len(obs_refs)}): {', '.join(obs_refs[:5])}...")
    print(f"Rationale:           {candidate.rationale_summary}")
    print("-" * 80)
    print("Evidence Gates & Safety Invariants:")
    for gname, gres in gate_results.items():
        print(f"  [{gres.status.value:<15}] {gname:<26}: {gres.details}")
    print("-" * 80)
    print(f"Overall Safety Gate Result: {'PASS' if passes_safety else 'NEEDS_REVIEW_OR_FAIL'}")
    print("=" * 80)
    return 0


def cmd_validate(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Validates an improvement candidate via GovernanceEngine."""
    candidate = store.get_improvement_candidate(args.candidate_id)
    if not candidate:
        print(f"Error: Candidate '{args.candidate_id}' not found.")
        return 1

    gov_engine = GovernanceEngine(store)
    success, validated_c, gate_results = gov_engine.validate_candidate(candidate)

    if args.json:
        print(json.dumps({
            "candidate_id": candidate.candidate_id,
            "success": success,
            "status": validated_c.status.value,
            "gates": {k: v.to_dict() for k, v in gate_results.items()},
        }, indent=2))
        return 0 if success else 1

    print("=" * 80)
    print(f"  Validation Result for: {candidate.candidate_id}")
    print("=" * 80)
    print(f"Outcome:   {'VALIDATED' if success else 'VALIDATION_FAILED'}")
    print(f"New State: {validated_c.status.value}")
    print("-" * 80)
    for gname, gres in gate_results.items():
        print(f"  [{gres.status.value:<15}] {gname:<26}: {gres.details}")
    print("-" * 80)
    return 0 if success else 1


def cmd_approve(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Executes explicit human approval to promote candidate to durable knowledge."""
    candidate = store.get_improvement_candidate(args.candidate_id)
    if not candidate:
        print(f"Error: Candidate '{args.candidate_id}' not found.")
        return 1

    scope_override = None
    if args.scope:
        try:
            scope_override = ExperienceScope(args.scope.lower())
        except ValueError:
            print(f"Error: Invalid scope '{args.scope}'.")
            return 1

    gov_engine = GovernanceEngine(store)
    try:
        durable, gov_rec = gov_engine.approve_candidate(
            candidate=candidate,
            reviewer_id=args.reviewer,
            reviewer_notes=args.notes or "CLI human approval",
            scope_override=scope_override,
            ttl_days=args.ttl_days,
        )
    except Exception as e:
        print(f"Approval failed: {e}")
        return 1

    if args.json:
        print(json.dumps({
            "knowledge_id": durable.knowledge_id,
            "governance_record_id": gov_rec.record_id,
            "status": durable.status.value,
            "normalized_statement": durable.normalized_statement,
            "review_due_timestamp": durable.review_due_at,
        }, indent=2))
        return 0

    print("=" * 80)
    print("  HUMAN APPROVAL RECORDED — DURABLE KNOWLEDGE PROMOTED")
    print("=" * 80)
    print(f"Knowledge ID:     {durable.knowledge_id}")
    print(f"Governance ID:    {gov_rec.record_id}")
    print(f"Reviewer:         {gov_rec.reviewer_id}")
    print(f"Scope:            {durable.scope.value}")
    print(f"Decision:         {gov_rec.decision.value}")
    print(f"Review Due:       {durable.review_due_at}")
    print(f"Statement:        {durable.normalized_statement}")
    print("=" * 80)
    return 0


def cmd_reject(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Rejects a candidate with explicit human reason."""
    candidate = store.get_improvement_candidate(args.candidate_id)
    if not candidate:
        print(f"Error: Candidate '{args.candidate_id}' not found.")
        return 1

    gov_engine = GovernanceEngine(store)
    try:
        rejected_c, gov_rec = gov_engine.reject_candidate(
            candidate=candidate,
            reviewer_id=args.reviewer,
            rejection_reason=args.reason,
        )
    except Exception as e:
        print(f"Rejection failed: {e}")
        return 1

    if args.json:
        print(json.dumps({
            "candidate_id": rejected_c.candidate_id,
            "status": rejected_c.status.value,
            "governance_record_id": gov_rec.record_id,
            "reviewer": gov_rec.reviewer_id,
            "reason": gov_rec.reviewer_notes,
        }, indent=2))
        return 0

    print(f"Candidate '{candidate.candidate_id}' successfully REJECTED by {args.reviewer}.")
    return 0


def cmd_decay(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Evaluates knowledge decay, staleness, and review dates."""
    decay_engine = KnowledgeDecayEngine(store)
    eval_result = decay_engine.evaluate_staleness()

    if args.apply:
        counts = decay_engine.apply_decay_transitions()
        eval_result["transitions_applied"] = counts

    if args.json:
        print(json.dumps(eval_result, indent=2))
        return 0

    print("=" * 80)
    print("  Knowledge Decay & Staleness Report")
    print("=" * 80)
    print(f"Active Durable Knowledge: {len(eval_result['active'])}")
    print(f"Review Due Knowledge:     {len(eval_result['review_due'])}")
    print(f"Stale Knowledge:          {len(eval_result['stale'])}")
    if "transitions_applied" in eval_result:
        print(f"Transitions Applied:      {eval_result['transitions_applied']}")
    print("-" * 80)

    if eval_result["review_due"]:
        print("Review Due Items:")
        for item in eval_result["review_due"]:
            print(f"  - [{item['knowledge_id']}] Due: {item['review_due']} | {item['statement']}")
        print("-" * 80)

    if eval_result["stale"]:
        print("Stale Items:")
        for item in eval_result["stale"]:
            print(f"  - [{item['knowledge_id']}] Staleness: {item['staleness_days']} days | {item['statement']}")
        print("-" * 80)

    return 0


def cmd_field_intel(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Executes the 12 descriptive Field Intelligence aggregate queries."""
    fi_engine = FieldIntelligenceEngine(store)
    report = fi_engine.generate_comprehensive_report(project_id=args.project)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print("=" * 80)
    print(f"  Desktop WebView Reviewer — Field Intelligence Report")
    print("=" * 80)
    print(f"Generated Timestamp:     {report.generated_at}")
    print(f"Scope / Project Filter:  {args.project or 'ALL_PROJECTS'}")
    print("-" * 80)

    print("\n1. Top Recurring Failure Signatures:")
    for f in report.top_recurring_failures[:5]:
        print(f"   [{f.get('occurrence_count', 0)}x] {f.get('signature')}")

    print("\n2. Failure Recurrence by Action Type:")
    for act in report.failures_by_action_type[:5]:
        print(f"   {act.get('action_type', 'UNKNOWN'):<24}: {act.get('failure_count', 0)} failures")

    print("\n3. Recovery Success by Strategy:")
    for strat in report.recovery_success_by_strategy[:5]:
        succ = strat.get("success_count", 0)
        tot = strat.get("total_attempts", 0)
        rate = strat.get("success_rate", 0.0) * 100.0
        print(f"   {strat.get('strategy_applied', 'UNKNOWN'):<24}: {rate:.1f}% ({succ}/{tot})")

    print("\n4. Verification Outcome Distribution:")
    for vout, cnt in report.verification_distribution.items():
        print(f"   {vout:<24}: {cnt}")

    print("\n5. Agent Tool Categories Associated with Failures:")
    for cat in report.agent_tool_failures[:5]:
        print(f"   {cat.get('tool_category', 'UNKNOWN'):<24}: {cat.get('failure_correlation_count', 0)} failures")

    print("\n6. User Corrections Associated with Failures:")
    for ctype in report.user_corrections[:5]:
        print(f"   {ctype.get('correction_type', 'UNKNOWN'):<24}: {ctype.get('occurrence_count', 0)} times")

    print("\n7. Most Frequent Improvement Candidates:")
    for cand in report.frequent_candidates[:5]:
        print(f"   [{cand.get('evidence_count', 0)}x] {cand.get('candidate_id')} ({cand.get('status')})")

    print(f"\n8. Durable Knowledge Due for Review: {len(report.knowledge_due_for_review)}")
    for d in report.knowledge_due_for_review[:3]:
        print(f"   - [{d.get('knowledge_id')}] {d.get('normalized_statement')}")

    print(f"\n9. Newly Emerging Patterns: {len(report.emerging_patterns)}")
    for p in report.emerging_patterns[:3]:
        print(f"   - [{p.get('occurrence_count', 0)}x] {p.get('pattern_type')}: {p.get('summary')}")

    print("=" * 80)
    return 0


def cmd_status(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Displays comprehensive aggregate counts across observations, patterns, candidates, durable knowledge, and governance."""
    try:
        counts = store.get_record_counts()
        observations = store.get_observations(limit=1000)
        patterns = store.get_patterns(limit=1000)
        candidates = store.get_improvement_candidates(limit=1000)
        durable_items = store.get_durable_knowledge(limit=1000)
        gov_records = store.get_governance_records(limit=1000)

        cand_by_status: Dict[str, int] = {}
        for c in candidates:
            st = c.status.value if hasattr(c.status, "value") else str(c.status)
            cand_by_status[st] = cand_by_status.get(st, 0) + 1

        decay_engine = KnowledgeDecayEngine(store)
        staleness = decay_engine.evaluate_staleness()

        data = {
            "observations_total": len(observations),
            "patterns_total": len(patterns),
            "candidates_total": len(candidates),
            "candidates_by_status": cand_by_status,
            "durable_knowledge_total": len(durable_items),
            "durable_active": len(staleness.get("active", [])),
            "durable_review_due": len(staleness.get("review_due", [])),
            "durable_stale": len(staleness.get("stale", [])),
            "governance_decisions_total": len(gov_records),
            "privacy_violations_blocked": LearningSafetyGate.blocked_violations_count(),
            "store_record_counts": counts,
        }

        if args.json:
            print(json.dumps(data, indent=2))
            return 0

        print("=" * 80)
        print("  Desktop WebView Reviewer — Learning & Governance Status")
        print("=" * 80)
        print(f"Observations Recorded:       {len(observations)}")
        print(f"Patterns Discovered:         {len(patterns)}")
        print(f"Improvement Candidates:      {len(candidates)}")
        for st, c_cnt in cand_by_status.items():
            print(f"  - {st:<25}: {c_cnt}")
        print(f"Durable Knowledge Total:     {len(durable_items)}")
        print(f"  - Active:                  {len(staleness.get('active', []))}")
        print(f"  - Review Due:              {len(staleness.get('review_due', []))}")
        print(f"  - Stale:                   {len(staleness.get('stale', []))}")
        print(f"Governance Records:          {len(gov_records)}")
        print(f"Privacy Violations Blocked:  {LearningSafetyGate.blocked_violations_count()}")
        print("=" * 80)
        return 0
    except Exception as e:
        logger.error("Failed to retrieve learning status: %s", e)
        print(f"Error: Unable to retrieve status: {e}")
        return 1


def cmd_run_observations(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Derives and records observations from failures, recoveries, and outcomes."""
    try:
        from runtime.experience.learning.observation_engine import LearningObservationEngine
        engine = LearningObservationEngine(store)
        recorded = 0

        failures = store.get_failures(limit=args.limit)
        for f in failures:
            obs = engine.create_observation_from_failure(f, project_id=args.project)
            if obs:
                store.record_observation(obs)
                recorded += 1

        recoveries = store.get_recovery_attempts(limit=args.limit)
        for r in recoveries:
            obs = engine.create_observation_from_recovery(r, project_id=args.project)
            if obs:
                store.record_observation(obs)
                recorded += 1

        outcomes = store.get_outcomes(limit=args.limit)
        for o in outcomes:
            obs = engine.create_observation_from_outcome(o, project_id=args.project)
            if obs:
                store.record_observation(obs)
                recorded += 1

        if args.json:
            print(json.dumps({
                "failures_evaluated": len(failures),
                "recoveries_evaluated": len(recoveries),
                "outcomes_evaluated": len(outcomes),
                "observations_recorded": recorded,
            }, indent=2))
            return 0

        print(f"Processed failures ({len(failures)}), recoveries ({len(recoveries)}), outcomes ({len(outcomes)}) -> Recorded {recorded} observations.")
        return 0
    except Exception as e:
        logger.error("run-observations failed: %s", e)
        print(f"Error executing run-observations: {e}")
        return 1


def cmd_run_patterns(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Discovers and records explainable patterns from accumulated observations."""
    try:
        from runtime.experience.learning.pattern_detector import DeterministicPatternDetector
        scope_val = ExperienceScope(args.scope.lower()) if args.scope else ExperienceScope.PROJECT
        observations = store.get_observations(limit=args.limit)
        patterns = DeterministicPatternDetector.detect_patterns(
            observations=observations,
            scope=scope_val,
            project_id=args.project,
        )
        recorded = 0
        for p in patterns:
            store.record_pattern(p)
            recorded += 1

        if args.json:
            print(json.dumps({
                "observations_evaluated": len(observations),
                "patterns_detected": len(patterns),
                "patterns_recorded": recorded,
            }, indent=2))
            return 0

        print(f"Evaluated {len(observations)} observations -> Detected & recorded {recorded} patterns.")
        return 0
    except Exception as e:
        logger.error("run-patterns failed: %s", e)
        print(f"Error executing run-patterns: {e}")
        return 1


def cmd_run_candidates(store: ExperienceStore, args: argparse.Namespace) -> int:
    """Synthesizes improvement candidates from detected patterns."""
    try:
        from runtime.experience.learning.candidate_generator import ImprovementCandidateGenerator
        patterns = store.get_patterns(limit=args.limit)
        generated = 0
        for pat in patterns:
            cand = ImprovementCandidateGenerator.generate_candidate(pat)
            store.record_improvement_candidate(cand)
            generated += 1

        if args.json:
            print(json.dumps({
                "patterns_evaluated": len(patterns),
                "candidates_generated": generated,
            }, indent=2))
            return 0

        print(f"Evaluated {len(patterns)} patterns -> Generated & recorded {generated} improvement candidates.")
        return 0
    except Exception as e:
        logger.error("run-candidates failed: %s", e)
        print(f"Error executing run-candidates: {e}")
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Desktop WebView Reviewer Learning, Governance & Field Intelligence CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # status
    p_status = subparsers.add_parser("status", help="Display aggregate learning, governance, and safety status")
    p_status.add_argument("--json", action="store_true", help="Output JSON")

    # report
    p_report = subparsers.add_parser("report", help="Display 12 descriptive aggregate field intelligence metrics (alias for field-intel)")
    p_report.add_argument("--project", help="Filter by project ID")
    p_report.add_argument("--json", action="store_true", help="Output JSON")

    # run-observations
    p_run_obs = subparsers.add_parser("run-observations", help="Derive and record observations from failures, recoveries, and outcomes")
    p_run_obs.add_argument("--limit", type=int, default=100, help="Maximum number of historical records to process (default: 100)")
    p_run_obs.add_argument("--project", help="Filter by project ID")
    p_run_obs.add_argument("--json", action="store_true", help="Output JSON")

    # run-patterns
    p_run_pat = subparsers.add_parser("run-patterns", help="Discover and record explainable patterns from accumulated observations")
    p_run_pat.add_argument("--limit", type=int, default=100, help="Maximum number of observations to evaluate (default: 100)")
    p_run_pat.add_argument("--scope", help="Pattern scope (project, session)")
    p_run_pat.add_argument("--project", help="Filter by project ID")
    p_run_pat.add_argument("--json", action="store_true", help="Output JSON")

    # run-candidates
    p_run_cand = subparsers.add_parser("run-candidates", help="Synthesize improvement candidates from detected patterns")
    p_run_cand.add_argument("--limit", type=int, default=100, help="Maximum number of patterns to evaluate (default: 100)")
    p_run_cand.add_argument("--json", action="store_true", help="Output JSON")

    # list
    p_list = subparsers.add_parser("list", help="List improvement candidates")
    p_list.add_argument("--status", help="Filter by status (OBSERVED, CANDIDATE, VALIDATED, DURABLE, etc.)")
    p_list.add_argument("--scope", help="Filter by scope (session, project, global)")
    p_list.add_argument("--limit", type=int, default=50, help="Maximum number of candidates to list")
    p_list.add_argument("--json", action="store_true", help="Output JSON")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect candidate record and evidence gate evaluations")
    p_inspect.add_argument("candidate_id", help="Candidate ID to inspect")
    p_inspect.add_argument("--json", action="store_true", help="Output JSON")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate candidate against evidence gates")
    p_validate.add_argument("candidate_id", help="Candidate ID to validate")
    p_validate.add_argument("--json", action="store_true", help="Output JSON")

    # approve
    p_approve = subparsers.add_parser("approve", help="Human approval to promote candidate to durable knowledge")
    p_approve.add_argument("candidate_id", help="Candidate ID to approve")
    p_approve.add_argument("--reviewer", required=True, help="Reviewer identity (mandatory)")
    p_approve.add_argument("--notes", help="Human approval notes")
    p_approve.add_argument("--scope", help="Approved scope override (session, project, global)")
    p_approve.add_argument("--ttl-days", type=int, default=30, help="Days before review is due (default: 30)")
    p_approve.add_argument("--json", action="store_true", help="Output JSON")

    # reject
    p_reject = subparsers.add_parser("reject", help="Reject candidate with human reason")
    p_reject.add_argument("candidate_id", help="Candidate ID to reject")
    p_reject.add_argument("--reviewer", required=True, help="Reviewer identity (mandatory)")
    p_reject.add_argument("--reason", required=True, help="Rejection rationale")
    p_reject.add_argument("--json", action="store_true", help="Output JSON")

    # decay
    p_decay = subparsers.add_parser("decay", help="Evaluate knowledge decay, staleness, and review deadlines")
    p_decay.add_argument("--apply", action="store_true", help="Apply state transitions (e.g. DURABLE -> REVIEW_DUE -> STALE)")
    p_decay.add_argument("--json", action="store_true", help="Output JSON")

    # field-intel
    p_intel = subparsers.add_parser("field-intel", help="Display 12 descriptive aggregate field intelligence metrics")
    p_intel.add_argument("--project", help="Filter by project ID")
    p_intel.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    try:
        store = ExperienceStore.get_default_store()
    except Exception as e:
        print(f"Error: Unable to access Experience Store: {e}")
        return 1

    if args.command == "status":
        return cmd_status(store, args)
    elif args.command in ("report", "field-intel"):
        return cmd_field_intel(store, args)
    elif args.command == "run-observations":
        return cmd_run_observations(store, args)
    elif args.command == "run-patterns":
        return cmd_run_patterns(store, args)
    elif args.command == "run-candidates":
        return cmd_run_candidates(store, args)
    elif args.command == "list":
        return cmd_list(store, args)
    elif args.command == "inspect":
        return cmd_inspect(store, args)
    elif args.command == "validate":
        return cmd_validate(store, args)
    elif args.command == "approve":
        return cmd_approve(store, args)
    elif args.command == "reject":
        return cmd_reject(store, args)
    elif args.command == "decay":
        return cmd_decay(store, args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
