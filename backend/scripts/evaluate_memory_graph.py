#!/usr/bin/env python3
"""Offline structural replay gate for the inspectable five-kernel memory graph."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int | float:
    value = conn.execute(sql, params).fetchone()[0]
    return value or 0


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def graph_latency(conn: sqlite3.Connection, samples: int = 40) -> dict:
    timings = []
    returned = 0
    for _ in range(samples):
        started = time.perf_counter()
        node_ids = [row[0] for row in conn.execute(
            "SELECT id FROM memory_nodes ORDER BY occurred_at DESC, id DESC LIMIT 300"
        ).fetchall()]
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            returned = len(conn.execute(
                f"SELECT id FROM memory_edges WHERE source_node_id IN ({placeholders}) "
                f"AND target_node_id IN ({placeholders})",
                tuple(node_ids) + tuple(node_ids),
            ).fetchall())
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    p95 = timings[min(len(timings) - 1, int((len(timings) - 1) * 0.95))]
    return {
        "samples": samples,
        "nodes": min(len(node_ids), 300),
        "edges": returned,
        "p50_ms": round(timings[len(timings) // 2], 3),
        "p95_ms": round(p95, 3),
    }


def evaluate(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        required = {
            "memory_nodes", "memory_facts", "memory_modules", "memory_claims",
            "memory_edges", "memory_synthesis_runs", "evidence_events", "kernel_states",
        }
        missing = sorted(name for name in required if not table_exists(conn, name))
        if missing:
            raise RuntimeError(f"memory graph migration is missing tables: {', '.join(missing)}")

        facts = scalar(conn, "SELECT COUNT(*) FROM memory_facts")
        modules = scalar(conn, "SELECT COUNT(*) FROM memory_modules")
        claims = scalar(conn, "SELECT COUNT(*) FROM memory_claims")
        current_claims = scalar(conn, """
            SELECT COUNT(*) FROM memory_claims c
            JOIN memory_nodes n ON n.id=c.node_id
            JOIN memory_modules m ON m.node_id=c.module_node_id
            WHERE n.status != 'legacy' AND m.module_type != 'legacy_import'
        """)
        supported_current_claims = scalar(conn, """
            SELECT COUNT(DISTINCT c.node_id) FROM memory_claims c
            JOIN memory_nodes n ON n.id=c.node_id
            JOIN memory_modules m ON m.node_id=c.module_node_id
            JOIN memory_edges e ON e.target_node_id=c.node_id AND e.relation_type='SUPPORTS'
            JOIN memory_facts f ON f.node_id=e.source_node_id
            WHERE n.status != 'legacy' AND m.module_type != 'legacy_import'
        """)
        cross_kernel_inputs = scalar(conn, """
            SELECT COUNT(*) FROM memory_edges e
            JOIN memory_nodes fact_node ON fact_node.id=e.source_node_id
            JOIN memory_nodes module_node ON module_node.id=e.target_node_id
            WHERE e.relation_type='CONSOLIDATED_INTO'
              AND fact_node.kernel_name != module_node.kernel_name
        """)
        reused_facts = scalar(conn, """
            SELECT COUNT(*) FROM (
              SELECT source_node_id FROM memory_edges
              WHERE relation_type='CONSOLIDATED_INTO'
              GROUP BY source_node_id HAVING COUNT(DISTINCT target_node_id) > 1
            )
        """)
        mutable_modules = scalar(conn, "SELECT COUNT(*) FROM memory_modules WHERE immutable != 1")
        duplicate_facts = scalar(conn, """
            SELECT COUNT(*) FROM (
              SELECT source_mutation_id, fact_ordinal FROM memory_facts
              GROUP BY source_mutation_id, fact_ordinal HAVING COUNT(*) > 1
            )
        """)
        sequence_duplicates = scalar(conn, """
            SELECT COUNT(*) FROM (
              SELECT learner_id, learner_seq FROM evidence_events
              WHERE learner_seq IS NOT NULL
              GROUP BY learner_id, learner_seq HAVING COUNT(*) > 1
            )
        """)
        correction_modules = scalar(
            conn, "SELECT COUNT(*) FROM memory_modules WHERE module_type='correction'"
        )
        correction_links = scalar(
            conn, "SELECT COUNT(*) FROM memory_edges WHERE relation_type='SUPERSEDES'"
        )
        conflicts = scalar(
            conn, "SELECT COUNT(*) FROM memory_edges WHERE relation_type='CONTRADICTS'"
        )
        stale_active = scalar(conn, """
            SELECT COUNT(*) FROM memory_nodes
            WHERE status='active' AND valid_to IS NOT NULL AND valid_to < CURRENT_TIMESTAMP
        """)
        field_units = scalar(conn, "SELECT COUNT(*) FROM kernel_states") * 2
        active_nodes = scalar(conn, "SELECT COUNT(*) FROM memory_nodes WHERE status='active'")
        usage_rows = conn.execute(
            "SELECT usage FROM memory_synthesis_runs WHERE status='completed'"
        ).fetchall()
        token_cost = 0
        for (raw,) in usage_rows:
            try:
                usage = json.loads(raw or "{}")
                token_cost += int(usage.get("total_tokens") or usage.get("total_token_count") or 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        coverage = 1.0 if current_claims == 0 else supported_current_claims / current_claims
        compression = 0.0 if facts == 0 else modules / facts
        latency = graph_latency(conn)
        acceptance = {
            "all_current_claims_have_fact_evidence": supported_current_claims == current_claims,
            "no_cross_kernel_module_inputs": cross_kernel_inputs == 0,
            "facts_consumed_at_most_once": reused_facts == 0,
            "modules_are_immutable": mutable_modules == 0,
            "corrections_preserve_history": correction_modules == 0 or correction_links >= correction_modules,
            "idempotent_fact_keys": duplicate_facts == 0,
            "learner_sequences_are_unique": sequence_duplicates == 0,
            "graph_query_p95_under_250ms": latency["p95_ms"] < 250,
        }
        return {
            "database": str(path),
            "variants": {
                "current_field_overwrite": {
                    "output_units": field_units,
                    "claim_level_evidence_coverage": 0.0,
                    "history_preserved": False,
                },
                "monolithic_summary": {
                    "output_units": int(bool(facts)),
                    "claim_level_evidence_coverage": 0.0,
                    "kernel_isolation": False,
                },
                "five_kernel_fact_graph": {
                    "facts": facts,
                    "modules": modules,
                    "claims": claims,
                    "active_nodes": active_nodes,
                    "claim_level_evidence_coverage": round(coverage, 4),
                    "module_to_fact_ratio": round(compression, 4),
                    "conflict_edges": conflicts,
                    "expired_but_active_nodes": stale_active,
                    "llm_total_tokens": token_cost,
                    "query_latency": latency,
                },
            },
            "acceptance": acceptance,
            "passed": all(acceptance.values()),
            "notes": {
                "legacy_imports": "Legacy/unverified modules are excluded from claim evidence coverage.",
                "semantic_quality": "Run labeled trajectory replay before enabling automatic synthesis.",
            },
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db", type=Path,
        default=Path(__file__).resolve().parents[1] / "learnflow.db",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.db.expanduser().resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

