"""
SQLAlchemy ORM models.

- Config: singleton row holding Instagram credentials
- Campaign: a Post ID + trigger keywords + reply/DM text + active toggle
- ProcessedComment: dedupe table so we never reply/DM twice for the same comment
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


class Config(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, index=True)
    access_token = Column(Text, nullable=True)
    page_id = Column(String(255), nullable=True)
    instagram_business_account_id = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(String(255), nullable=False, index=True)
    post_thumbnail_url = Column(Text, nullable=True)
    post_caption = Column(Text, nullable=True)
    keywords = Column(Text, nullable=False)  # comma-separated
    comment_reply_text = Column(Text, nullable=False)
    dm_message_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def keyword_list(self):
        return [k.strip().lower() for k in self.keywords.split(",") if k.strip()]


class ProcessedComment(Base):
    __tablename__ = "processed_comments"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(String(255), unique=True, nullable=False, index=True)
    campaign_id = Column(Integer, nullable=True)
    commenter_id = Column(String(255), nullable=True)
    status = Column(String(50), default="processed")  # processed, failed, skipped
    detail = Column(Text, nullable=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
