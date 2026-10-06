from app.core.db import SessionLocal


def get_db():
    with SessionLocal() as session:
        yield session
