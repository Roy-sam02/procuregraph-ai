"""Append a verified workflow outcome once and read it within its tenant."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from psycopg import Connection

if TYPE_CHECKING:
    from apps.api.app.agents.investigation_workflow import InvestigationResult


def _payload(result: InvestigationResult, tenant: UUID, invoice: UUID,
             line: UUID, actor: str) -> dict:
    if result.status not in {"complete", "needs_review", "abstained"}:
        raise ValueError("Invalid investigation status")
    finding = result.finding
    if result.status == "abstained":
        if finding is not None or result.error_code not in {
            "PRICE_SOURCE_UNAVAILABLE", "DOCUMENT_UNAVAILABLE",
            "GRAPH_UNAVAILABLE", "EVIDENCE_CONFLICT",
        }:
            raise ValueError("Abstention must contain a known error and no finding")
    elif (finding is None or result.error_code is not None
          or finding.tenant_id != str(tenant)
          or finding.invoice_id != str(invoice)
          or finding.invoice_line_id != str(line)
          or finding.is_violation != (result.status == "needs_review")
          or not finding.document_sha256 or len(finding.graph_edge_ids) != 4):
        raise ValueError("Completed investigation needs matching verified evidence")
    return {"tenant_id": str(tenant), "invoice_id": str(invoice),
            "invoice_line_id": str(line), "created_by": actor,
            "status": result.status, "error_code": result.error_code,
            "finding": asdict(finding) if finding is not None else None}


def record_investigation(connection: Connection, tenant: UUID, invoice: UUID,
                         line: UUID, actor: str, key: str,
                         result: InvestigationResult) -> UUID:
    """A reused tenant/key returns its original ID only for identical content."""
    if any(type(value) is not UUID for value in (tenant, invoice, line)):
        raise ValueError("Investigation IDs must be UUIDs")
    if not actor or len(actor) > 128 or not 16 <= len(key) <= 128 or not key.isascii():
        raise ValueError("Invalid local actor or idempotency key")
    payload = _payload(result, tenant, invoice, line, actor)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"))
                            .encode("utf-8")).hexdigest()
    proposed = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO investigations
                    (id, tenant_id, invoice_id, invoice_line_id, idempotency_key,
                     payload_hash, created_by, status, error_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                RETURNING id
            """, (proposed, tenant, invoice, line, key, digest, actor,
                  result.status, result.error_code))
            inserted = cursor.fetchone()
            if inserted is not None and result.finding is not None:
                cursor.execute("""
                    INSERT INTO findings
                        (id, investigation_id, rule_id, is_violation, evidence_json)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                """, (uuid4(), proposed, result.finding.rule_id,
                      result.finding.is_violation, json.dumps(payload["finding"])))
            if inserted is not None:
                return inserted[0]
            cursor.execute("""
                SELECT id, payload_hash FROM investigations
                WHERE tenant_id = %s AND idempotency_key = %s
            """, (tenant, key))
            existing = cursor.fetchone()
            if existing is None or existing[1] != digest:
                raise ValueError("Idempotency key was reused for different content")
            return existing[0]


def read_investigation(connection: Connection, tenant: UUID, investigation_id: UUID) -> dict | None:
    """The tenant predicate applies before any finding evidence is returned."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT i.id, i.tenant_id, i.invoice_id, i.invoice_line_id,
                   i.created_by, i.status, i.error_code, i.created_at,
                   f.id, f.evidence_json
            FROM investigations i
            LEFT JOIN findings f ON f.investigation_id = i.id
            WHERE i.tenant_id = %s AND i.id = %s
        """, (tenant, investigation_id))
        row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "tenant_id": str(row[1]),
            "invoice_id": str(row[2]), "invoice_line_id": str(row[3]),
            "created_by": row[4], "status": row[5], "error_code": row[6],
            "created_at": row[7].isoformat(), "finding_id": str(row[8]) if row[8] else None,
            "finding": row[9]}


def read_review_queue(connection: Connection, tenant: UUID, limit: int = 10) -> list[dict]:
    """List only bounded, verified price violations awaiting human review."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Review queue limit must be between 1 and 20")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT i.id, i.invoice_id, i.invoice_line_id, i.created_at,
                   f.id, f.rule_id,
                   f.evidence_json->>'currency', f.evidence_json->>'excess_amount'
            FROM investigations i
            JOIN findings f ON f.investigation_id = i.id
            LEFT JOIN approvals a ON a.finding_id = f.id
            WHERE i.tenant_id = %s AND i.status = 'needs_review'
              AND f.is_violation = TRUE AND a.id IS NULL
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT %s
        """, (tenant, limit))
        rows = cursor.fetchall()
    return [{"id": str(row[0]), "invoice_id": str(row[1]),
             "invoice_line_id": str(row[2]), "created_at": row[3].isoformat(),
             "finding_id": str(row[4]), "rule_id": row[5], "currency": row[6],
             "excess_amount": row[7], "status": "needs_review"} for row in rows]


def record_approval(connection: Connection, tenant: UUID, finding_id: UUID,
                    actor_id: UUID, decision: str, reason: str, key: str) -> UUID:
    """Record a final human decision once, with tenant and retry checks."""
    if any(type(value) is not UUID for value in (tenant, finding_id, actor_id)):
        raise ValueError("Approval IDs must be UUIDs")
    if decision not in ("approved", "rejected") or not isinstance(reason, str):
        raise ValueError("Invalid decision or reason")
    reason = reason.strip()
    if not 1 <= len(reason) <= 1000 or not isinstance(key, str) or not 16 <= len(key) <= 128 or not key.isascii():
        raise ValueError("Invalid reason or idempotency key")
    proposed = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT f.id FROM findings f
                JOIN investigations i ON i.id = f.investigation_id
                WHERE f.id = %s AND i.tenant_id = %s
                  AND i.status = 'needs_review' AND f.is_violation = TRUE
                FOR UPDATE OF f
            """, (finding_id, tenant))
            if cursor.fetchone() is None:
                raise ValueError("Verified finding is unavailable to this tenant")
            cursor.execute("""
                INSERT INTO approvals
                    (id, tenant_id, finding_id, actor_id, decision, reason, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING RETURNING id
            """, (proposed, tenant, finding_id, actor_id, decision, reason, key))
            inserted = cursor.fetchone()
            if inserted is not None:
                return inserted[0]
            cursor.execute("""
                SELECT id, finding_id, actor_id, decision, reason
                FROM approvals WHERE tenant_id = %s AND idempotency_key = %s
            """, (tenant, key))
            existing = cursor.fetchone()
            if existing is None or existing[1:] != (finding_id, actor_id, decision, reason):
                raise ValueError("Finding was already decided or key reused for different content")
            return existing[0]
