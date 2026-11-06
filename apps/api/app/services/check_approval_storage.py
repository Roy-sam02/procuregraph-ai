"""Exercise approval storage in a rolled-back transaction against the synthetic case."""

import os
from uuid import UUID, uuid4

import psycopg

from apps.api.app.agents.investigation_records import read_review_queue, record_approval
from datasets.generator.seed_price_case import database_id


class RollBackCheck(Exception):
    pass


def main() -> None:
    tenant = database_id("DEMO-001", "TENANT")
    try:
        with psycopg.connect(host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
                             dbname="procuregraph", user="postgres",
                             password=os.environ["PROCUREGRAPH_DB_PASSWORD"]) as connection:
            with connection.transaction():
                queue = read_review_queue(connection, tenant)
                if len(queue) != 1:
                    raise ValueError("Expected exactly one undecided synthetic finding")
                finding = UUID(queue[0]["finding_id"])
                actor, key = uuid4(), "local-approval-check-0001"
                decision_id = record_approval(connection, tenant, finding, actor,
                                              "rejected", "Synthetic price discrepancy", key)
                if record_approval(connection, tenant, finding, actor, "rejected",
                                   "Synthetic price discrepancy", key) != decision_id:
                    raise ValueError("Idempotent retry returned a different decision")
                if read_review_queue(connection, tenant):
                    raise ValueError("Decided finding remained in the review queue")
                for invalid in ((UUID(int=0), finding, actor, "rejected", key),
                                (tenant, finding, actor, "approved", "different-key-000001")):
                    try:
                        record_approval(connection, invalid[0], invalid[1], invalid[2],
                                        invalid[3], "Synthetic price discrepancy", invalid[4])
                    except ValueError:
                        pass
                    else:
                        raise ValueError("Unauthorized or conflicting decision was accepted")
                for statement in ("UPDATE approvals SET reason = 'changed' WHERE id = %s",
                                  "DELETE FROM approvals WHERE id = %s"):
                    try:
                        with connection.transaction():
                            with connection.cursor() as cursor:
                                cursor.execute(statement, (decision_id,))
                    except psycopg.errors.RaiseException:
                        pass
                    else:
                        raise ValueError("Stored decision was mutated")
                raise RollBackCheck
    except RollBackCheck:
        pass
    print("PASS: tenant check, retry, queue removal and immutable decision; transaction rolled back")


if __name__ == "__main__":
    main()
