from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import config

Base = declarative_base()


class MemeImage(Base):
    __tablename__ = "meme_images"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    filepath = Column(String)
    text_content = Column(Text, nullable=True)
    description = Column(Text)
    tags = Column(JSON)
    title = Column(Text)
    upload_time = Column(DateTime, default=datetime.utcnow)
    file_hash = Column(String, unique=True)
    discord_url = Column(String, nullable=True)
    analysis_status = Column(String, default="pending")
    retry_count = Column(Integer, default=0)
    last_retry = Column(DateTime, nullable=True)


# Database engine / session
engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
