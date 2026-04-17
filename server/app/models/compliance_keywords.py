from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ComplianceKeyword(Base):
    __tablename__ = "compliance_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # 政治/暴力/色情/其他
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # low/medium/high
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
