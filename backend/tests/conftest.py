import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.live tests unless -m live is explicitly passed."""
    if "live" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="live test — run with: pytest -m live")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session
    Base.metadata.drop_all(engine)
