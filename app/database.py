from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}  # Required for SQLite
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    from app.models import models  # Import models to register them
    Base.metadata.create_all(bind=engine)

    # Run migrations for new columns (SQLite doesn't support ALTER TABLE ADD COLUMN with defaults easily)
    _migrate_placeholder_columns()


def _migrate_placeholder_columns():
    """Add missing columns to placeholders table for backwards compatibility."""
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('placeholders')]

    new_columns = {
        'content_type': "VARCHAR(20) DEFAULT 'text'",
        'multi_line': "INTEGER DEFAULT 0",
        'style': "TEXT"  # JSON stored as TEXT in SQLite
    }

    with engine.connect() as conn:
        for col_name, col_def in new_columns.items():
            if col_name not in columns:
                try:
                    conn.execute(text(f"ALTER TABLE placeholders ADD COLUMN {col_name} {col_def}"))
                    conn.commit()
                    print(f"Added column '{col_name}' to placeholders table")
                except Exception as e:
                    print(f"Could not add column '{col_name}': {e}")
