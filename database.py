"""
Database session setup for the Instagram automation tool.
Uses SQLite by default (file-based, zero-config). Swap DATABASE_URL in .env
to a Postgres URL later and nothing else needs to change.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# check_same_thread is only needed for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once on app startup."""
    # Import models here so they're registered on Base.metadata before create_all
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
