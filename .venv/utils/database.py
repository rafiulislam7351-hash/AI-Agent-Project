import os

import psycopg2
from psycopg2 import sql


class dbutil:
    def __init__(self, dbconfig, statement_timeout_ms=15000, max_rows=100):
        self.dbconfig = dbconfig
        self.statement_timeout_ms = statement_timeout_ms
        self.max_rows = max_rows
        self.connection = None
        self._connect()  # raises on failure instead of silently leaving None

    # ------------------------------------------------------------------
    def _connect(self):
        """Open a READ-ONLY, autocommit connection with a statement timeout.
        Autocommit means a failed query never leaves the connection stuck in an
        'aborted transaction' state, which is what lets the retry loop work."""
        conn = psycopg2.connect(**self.dbconfig)
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = %s", (self.statement_timeout_ms,))
        self.connection = conn

    def _ensure_connection(self):
        """Reconnect if the connection was closed or dropped."""
        if self.connection is None or self.connection.closed:
            self._connect()

    # ------------------------------------------------------------------
    def schema_details(self, schema_name, include_samples=True):
        """Return tables, columns, and (optionally) sample rows as text for the LLM.
        Note: sample rows are sent to your LLM provider. Use include_samples=False
        if the tables contain sensitive data."""
        self._ensure_connection()
        schema_details = ""

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name;",
                    (schema_name,),
                )
                tables_list = cursor.fetchall()

                for (table_name,) in tables_list:
                    schema_details += f"Table Name: {table_name}\n"
                    schema_details += f"Schema Name: {schema_name}\n"

                    cursor.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s "
                        "ORDER BY ordinal_position;",
                        (schema_name, table_name),
                    )
                    for column_name, data_type in cursor.fetchall():
                        schema_details += f"Columns: {column_name}    Data Types: {data_type}\n"

                    if include_samples:
                        try:
                            cursor.execute(
                                sql.SQL("SELECT * FROM {}.{} LIMIT 5;").format(
                                    sql.Identifier(schema_name),
                                    sql.Identifier(table_name),
                                )
                            )
                            schema_details += "Sample Data:\n"
                            for row in cursor.fetchall():
                                schema_details += f"Sample Row: {row}\n"
                        except psycopg2.Error as e:
                            print(f"Could not fetch sample data for {table_name}: {e}")

                    schema_details += "\n"  # blank line between tables

        except psycopg2.Error as e:
            print(f"Database error: {e}")

        return schema_details

    # ------------------------------------------------------------------
    def execute_sql(self, query):
        """Run a query and return columns + rows as a string.
        Database errors are RAISED (not swallowed) so the agent's repair loop
        can feed them back to the LLM. The connection is kept open for reuse."""
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(self.max_rows)
        return str({"columns": columns, "rows": rows})

    # Backwards-compatible alias for the old method name
    execute_query = execute_sql

    def close(self):
        if self.connection is not None and not self.connection.closed:
            self.connection.close()


# Only runs when you execute this file directly (NOT when it's imported).
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    obj = dbutil({
        "host": os.environ["host"],
        "port": os.environ["port"],
        "database": os.environ["database"],
        "user": os.environ["user"],
        "password": os.environ["password"],
    })

    with open("schema_details.txt", "w", encoding="utf-8") as f:
        f.write(obj.schema_details("public"))
    print("Wrote schema_details.txt")
    obj.close()