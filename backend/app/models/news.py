from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, PrimaryKeyConstraint, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.db import Base

_DT = DateTime(timezone=False)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # "rss" | "api"
    url_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_official: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")
    fetch_runs: Mapped[list["FetchRun"]] = relationship(back_populates="source")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),
        Index("ix_articles_canonical_url", "canonical_url"),
        Index("ix_articles_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    publisher: Mapped[str | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(nullable=False)
    summary_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(nullable=False)
    canonical_url: Mapped[str] = mapped_column(nullable=False)
    published_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
    tickers_raw: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    content_hash: Mapped[str | None] = mapped_column(nullable=True)
    raw_payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)

    # Sprint 2: sanitization + injection scan
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    injection_score: Mapped[float | None] = mapped_column(nullable=True)
    matched_rules: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="active")

    source: Mapped["Source"] = relationship(back_populates="articles")
    cluster_memberships: Mapped[list["ClusterMember"]] = relationship(
        back_populates="article"
    )


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(_DT, nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="running")
    items_seen: Mapped[int] = mapped_column(default=0)
    items_new: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    newest_item_at: Mapped[datetime | None] = mapped_column(_DT, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="fetch_runs")


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    primary_ticker: Mapped[str | None] = mapped_column(nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
    article_count: Mapped[int] = mapped_column(nullable=False, default=0)
    publisher_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # Sprint 3: LLM classification
    event_type: Mapped[str | None] = mapped_column(nullable=True)
    is_main_subject: Mapped[bool | None] = mapped_column(nullable=True)
    is_opinion: Mapped[bool | None] = mapped_column(nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(nullable=True)
    visible: Mapped[bool] = mapped_column(nullable=False, default=True)
    classification_model: Mapped[str | None] = mapped_column(nullable=True)
    classification_prompt_version: Mapped[str | None] = mapped_column(nullable=True)

    members: Mapped[list["ClusterMember"]] = relationship(back_populates="cluster")
    story: Mapped["Story | None"] = relationship(back_populates="cluster", uselist=False)


class ClusterMember(Base):
    __tablename__ = "cluster_members"
    __table_args__ = (
        PrimaryKeyConstraint("cluster_id", "article_id"),
        Index("ix_cluster_members_article_id", "article_id"),
    )

    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("story_clusters.id"), nullable=False
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False
    )
    match_method: Mapped[str] = mapped_column(nullable=False)  # "exact_hash" | "minhash"
    similarity: Mapped[float] = mapped_column(nullable=False)
    needs_llm_check: Mapped[bool] = mapped_column(nullable=False, default=False)

    cluster: Mapped["StoryCluster"] = relationship(back_populates="members")
    article: Mapped["Article"] = relationship(back_populates="cluster_memberships")


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (UniqueConstraint("cluster_id", name="uq_stories_cluster_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("story_clusters.id"), nullable=False)
    title_bg: Mapped[str] = mapped_column(Text, nullable=False)
    summary_bg: Mapped[str] = mapped_column(Text, nullable=False)
    tickers: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    event_type: Mapped[str | None] = mapped_column(nullable=True)
    is_opinion: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_status: Mapped[str] = mapped_column(nullable=False, default="pending")
    model_version: Mapped[str] = mapped_column(nullable=False)
    prompt_version: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_DT, nullable=False)

    cluster: Mapped["StoryCluster"] = relationship(back_populates="story")
    facts: Mapped[list["StoryFact"]] = relationship(back_populates="story")


class StoryFact(Base):
    __tablename__ = "story_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    fact_order: Mapped[int] = mapped_column(nullable=False)
    text_bg: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(nullable=False, default="pending")
    # values: "pending" | "verified" | "partially_supported" | "removed"

    story: Mapped["Story"] = relationship(back_populates="facts")
    evidence: Mapped[list["FactEvidence"]] = relationship(back_populates="fact")
    verification_logs: Mapped[list["VerificationLog"]] = relationship(back_populates="fact")


class FactEvidence(Base):
    __tablename__ = "fact_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("story_facts.id"), nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), nullable=False)
    quote_en: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int | None] = mapped_column(nullable=True)
    quote_end: Mapped[int | None] = mapped_column(nullable=True)

    fact: Mapped["StoryFact"] = relationship(back_populates="evidence")
    article: Mapped["Article"] = relationship()


class VerificationLog(Base):
    __tablename__ = "verification_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    fact_id: Mapped[int | None] = mapped_column(ForeignKey("story_facts.id"), nullable=True)
    check: Mapped[str] = mapped_column(nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DT, nullable=False)

    story: Mapped["Story"] = relationship()
    fact: Mapped["StoryFact | None"] = relationship(back_populates="verification_logs")


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(nullable=False)  # "classify" | "dedup_check"
    model: Mapped[str] = mapped_column(nullable=False)
    prompt_version: Mapped[str] = mapped_column(nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[float] = mapped_column(nullable=False)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)  # "ok" | "rejected" | "budget_exceeded"
    created_at: Mapped[datetime] = mapped_column(_DT, nullable=False)
