from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    input_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_stack: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_calls_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_agent_started", "agent_name", "started_at"),
        Index("ix_agent_runs_state_started", "state", "started_at"),
    )
