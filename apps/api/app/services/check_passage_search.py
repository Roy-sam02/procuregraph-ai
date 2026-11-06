"""Live, read-only checks for the synthetic PostgreSQL passage search."""

import os
from uuid import UUID

import psycopg

from apps.api.app.services.passage_search import search_passages
from datasets.generator.seed_price_case import database_id


def check() -> None:
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        tenant = database_id("DEMO-001", "TENANT")
        tolerance = search_passages(connection, tenant, "tolerance", top_k=1)
        assert len(tolerance) == 1 and tolerance[0]["clause"] == "2.2", tolerance
        assert tolerance[0]["page"] == 1 and tolerance[0]["score"] > 0, tolerance
        assert tolerance[0]["document_id"] == str(database_id("DEMO-001", "CON-001/document/v1"))
        dates = search_passages(connection, tenant, "effective period", top_k=1)
        assert len(dates) == 1 and dates[0]["clause"] == "2.3", dates
        assert search_passages(connection, database_id("OTHER", "TENANT"), "tolerance") == []
        print("PASS: tenant-scoped PostgreSQL full-text search returned clauses 2.2 and 2.3")

        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM document_chunks WHERE document_id = %s",
                           (database_id("DEMO-001", "CON-001/document/v1"),))
            assert cursor.fetchone()[0] == 3
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE document_chunks SET text_hash = text_hash WHERE id = %s",
                                   (UUID(tolerance[0]["source_id"]),))
        except psycopg.Error as exc:
            assert exc.sqlstate == "P0001", exc
        else:
            raise AssertionError("Append-only chunks incorrectly accepted an UPDATE")
        print("PASS: three source-linked chunks exist and PostgreSQL rejected a mutation")


if __name__ == "__main__":
    check()
