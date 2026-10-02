from sqlalchemy import (
    String,
    Boolean,
    Text,
    DateTime,
    ForeignKey
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship
)

from datetime import datetime


# ==================================================
# BASE
# ==================================================

class Base(DeclarativeBase):
    pass


# ==================================================
# USER
# ==================================================

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(100)
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(255)
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )


# ==================================================
# ENTITY
# ==================================================

class Entity(Base):

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True
    )

    entity_type: Mapped[str] = mapped_column(
        String(100),
        index=True
    )

    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    website: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # --------------------------------------------------
    # RELATIONSHIPS
    # --------------------------------------------------

    outgoing_relationships: Mapped[list["EntityRelationship"]] = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.source_entity_id",
        back_populates="source_entity",
        cascade="all, delete-orphan"
    )

    incoming_relationships: Mapped[list["EntityRelationship"]] = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.target_entity_id",
        back_populates="target_entity",
        cascade="all, delete-orphan"
    )


# ==================================================
# ENTITY RELATIONSHIP
# ==================================================

class EntityRelationship(Base):

    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    # --------------------------------------------------
    # SOURCE ENTITY
    # --------------------------------------------------

    source_entity_id: Mapped[int] = mapped_column(
        ForeignKey(
            "entities.id",
            ondelete="CASCADE"
        ),
        index=True
    )

    # --------------------------------------------------
    # TARGET ENTITY
    # --------------------------------------------------

    target_entity_id: Mapped[int] = mapped_column(
        ForeignKey(
            "entities.id",
            ondelete="CASCADE"
        ),
        index=True
    )

    # --------------------------------------------------
    # RELATIONSHIP TYPE
    # --------------------------------------------------

    relationship_type: Mapped[str] = mapped_column(
        String(100),
        index=True
    )

    # --------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # --------------------------------------------------
    # TIMESTAMPS
    # --------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # --------------------------------------------------
    # SQLALCHEMY RELATIONSHIPS
    # --------------------------------------------------

    source_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[source_entity_id],
        back_populates="outgoing_relationships"
    )

    target_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[target_entity_id],
        back_populates="incoming_relationships"
    )