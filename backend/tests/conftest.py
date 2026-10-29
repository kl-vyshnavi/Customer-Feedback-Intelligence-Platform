import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, get_db


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(main, "engine", engine)

    def override_get_db():
        from sqlalchemy.orm import Session

        with Session(engine, expire_on_commit=False) as session:
            yield session

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    engine.dispose()
