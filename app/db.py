import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


default_dir = Path(os.getenv("LUMI_DATA_DIR", Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi"))
database_url = os.getenv("DATABASE_URL")
if not database_url:
    default_dir.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{(default_dir / 'lumi.db').as_posix()}"
engine = create_engine(database_url)

if database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

Session = sessionmaker(engine)
