"""SQLAlchemy declarative metadata."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for Watchtower ORM models."""

    metadata = MetaData(schema="watchtower")
