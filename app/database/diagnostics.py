"""Useful application-level PostgreSQL diagnostics."""

from psycopg import sql

from app.database.migrations import EXPECTED_TABLES


def run_database_diagnostic(db):
    with db.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database, current_schema() AS schema, version() AS server_version"
            )
            server = dict(cursor.fetchone())
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                """,
                (list(EXPECTED_TABLES),),
            )
            available = {row["table_name"] for row in cursor.fetchall()}
            counts = {}
            for table_name in EXPECTED_TABLES:
                if table_name not in available:
                    continue
                cursor.execute(sql.SQL("SELECT COUNT(*) AS total FROM {}").format(sql.Identifier(table_name)))
                counts[table_name] = int(cursor.fetchone()["total"])
    missing = sorted(set(EXPECTED_TABLES) - available)
    return {
        "ok": not missing and db.obter_schema_version() == db.schema_version,
        "target": db.safe_target,
        "database": server["database"],
        "schema": server["schema"],
        "server_version": server["server_version"],
        "schema_version": db.obter_schema_version(),
        "missing_tables": missing,
        "tabelas": counts,
    }

