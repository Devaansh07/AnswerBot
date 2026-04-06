from pathlib import Path

import duckdb


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    db_path = project_root / "answerbot.duckdb"
    schema_path = project_root / "backend" / "sql" / "schema_duckdb.sql"

    con = duckdb.connect(str(db_path))
    sql = schema_path.read_text(encoding="utf-8")
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        con.execute(f"{stmt};")
    con.close()

    print(f"Initialized DuckDB at: {db_path}")
    print(f"Applied schema from: {schema_path}")


if __name__ == "__main__":
    main()
