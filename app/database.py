import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Postgres (or any SQLAlchemy-compatible URL you provide)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    # Local fallback so the app runs before you wire up psql
    engine = create_engine(
        "sqlite:///./dev.db", connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
