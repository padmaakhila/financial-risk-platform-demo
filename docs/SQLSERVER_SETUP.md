# Optional: SQL Server Express instead of SQLite

**Status: written for completeness and NOT tested in the build environment.** SQLite is the supported default. Try this only if you want it.

SSMS (SQL Server Management Studio) is just a client. You also need the **database engine**.

1. Install **SQL Server Express** (free edition) from Microsoft and choose the *Basic* install. Note the instance name, usually `localhost\SQLEXPRESS`.
2. Install **ODBC Driver 18 for SQL Server** (Microsoft).
3. In SSMS connect to `localhost\SQLEXPRESS` (Windows authentication), right-click Databases > New Database > name `aprisk`.
4. In the project: `pip install pyodbc`.
5. In `.env` set (Windows authentication, local development only):
   ```
   DATABASE_URL=mssql+pyodbc://@localhost\SQLEXPRESS/aprisk?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
   ```
   For SQL authentication use `mssql+pyodbc://USER:PASSWORD@host/aprisk?driver=ODBC+Driver+18+for+SQL+Server` and keep the password out of source control.
6. `python -m scripts.init_db` then `python -m scripts.seed_database`.

Notes and limits
- The code uses portable SQLAlchemy constructs; SQLite-only PRAGMAs are applied only to SQLite. Money is stored as exact decimal text on every database.
- JSON columns are stored as text on SQL Server. Row-level locking is better than SQLite, so several workers become possible; the queue claim is an atomic conditional UPDATE, which SQL Server supports.
- LangGraph's SQLite checkpointer (if you use `sqlite_checkpointer`) keeps its own small SQLite file; it does not need SQL Server.
- Alembic: `migrations/versions/0001_baseline.py` creates the schema from the models. For later changes create real revisions (`alembic revision --autogenerate`). Express has a 10 GB database size limit.
- Not verified: performance, the `ESCAPE` clause used for the `DOC_%` exception filter, and `ilike` search behaviour (SQL Server comparisons are usually case-insensitive by default collation).
