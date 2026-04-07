from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, Text, create_engine, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

try:
    import duckdb_engine  # noqa: F401
except ImportError as exc:
    raise RuntimeError(
        "DuckDB support requires `duckdb` and `duckdb-engine` to be installed."
    ) from exc


project_root = Path(__file__).resolve().parent.parent.parent
db_path = project_root / "answerbot.duckdb"

engine = create_engine(
    f"duckdb:///{db_path}",
    connect_args={"preload_extensions": ["fts"]}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=False)
    file_name = Column(Text, nullable=False)
    upload_time = Column(Text, nullable=False, default=_utcnow_iso)

    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))
    page_number = Column(Integer)
    section = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    image_path = Column(Text, nullable=True)

    document = relationship("Document", back_populates="chunks")


def _load_fts_extension():
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql("INSTALL fts;")
        except Exception:
            pass
        try:
            conn.exec_driver_sql("LOAD fts;")
        except Exception:
            pass


def refresh_fts_index():
    _load_fts_extension()
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql("PRAGMA drop_fts_index('document_chunks');")
        except Exception as e:
            pass

        try:
            conn.exec_driver_sql(
                "PRAGMA create_fts_index('document_chunks', 'id', 'content');"
            )
        except Exception as e:
            print("FTS index creation failed:", e)


def init_db():
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    file_name TEXT,
                    upload_time TEXT
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    page_number INTEGER,
                    section TEXT,
                    content TEXT,
                    image_path TEXT
                );
                """
            )
        )
    refresh_fts_index()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
