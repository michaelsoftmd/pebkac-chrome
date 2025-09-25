from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
from typing import Generator, Dict, Any, List, Optional
import json
import os

from app.core.config import get_settings

settings = get_settings()

# Create engine with proper SQLite URL (3 slashes for absolute path)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class ResearchSession(Base):
    __tablename__ = "research_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String, unique=True, index=True)
    topic = Column(String, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    data = Column(JSON)
    status = Column(String, default="pending")

class CollectedPost(Base):
    __tablename__ = "collected_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    publication = Column(String, index=True)
    title = Column(String)
    author = Column(String)
    published_date = Column(String)
    collected_at = Column(DateTime, server_default=func.now())
    content = Column(Text)
    data = Column(JSON)

# Database initialization
def init_db():
    """Create all tables"""
    # Ensure directory exists for sqlite databases
    if "sqlite" in settings.database_url:
        db_path = settings.database_url.replace("sqlite:///", "/")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    Base.metadata.create_all(bind=engine)

def get_db() -> Generator[Session, None, None]:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Repository pattern for cleaner data access
class ResearchRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_session(self, workflow_id: str, topic: str, data: dict) -> ResearchSession:
        """Create new research session"""
        session = ResearchSession(
            workflow_id=workflow_id,
            topic=topic,
            data=data
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session
    
    def get_session(self, workflow_id: str) -> ResearchSession:
        """Get research session by ID"""
        return self.db.query(ResearchSession).filter(
            ResearchSession.workflow_id == workflow_id
        ).first()
    
    def update_session(self, workflow_id: str, data: dict, status: str = None):
        """Update research session"""
        session = self.get_session(workflow_id)
        if session:
            session.data = data
            if status:
                session.status = status
            self.db.commit()
        return session

# Simplified DatabaseManager for compatibility
class DatabaseManager:
    """Database manager with simpler interface"""
    
    def __init__(self):
        self.db_url = get_settings().database_url
    
    def save_research_session(self, workflow_id: str, topic: str, data: Dict[str, Any]):
        """Save research session data"""
        db = next(get_db())
        try:
            repo = ResearchRepository(db)
            existing = repo.get_session(workflow_id)
            if existing:
                repo.update_session(workflow_id, data)
            else:
                repo.create_session(workflow_id, topic, data)
        finally:
            db.close()
    
    def get_research_sessions(self, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get research sessions"""
        db = next(get_db())
        try:
            if workflow_id:
                sessions = db.query(ResearchSession).filter(
                    ResearchSession.workflow_id == workflow_id
                ).all()
            else:
                sessions = db.query(ResearchSession).order_by(
                    ResearchSession.created_at.desc()
                ).limit(limit).all()
            
            return [
                {
                    "id": s.id,
                    "workflow_id": s.workflow_id,
                    "topic": s.topic,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "status": s.status,
                    "data": s.data
                }
                for s in sessions
            ]
        finally:
            db.close()
    
    def save_collected_post(self, post_data: Dict[str, Any]):
        """Save collected post data"""
        db = next(get_db())
        try:
            post = CollectedPost(
                url=post_data.get('url'),
                publication=post_data.get('publication'),
                title=post_data.get('title'),
                author=post_data.get('author'),
                published_date=post_data.get('published_date'),
                content=post_data.get('content'),
                data=post_data
            )
            db.add(post)
            db.commit()
        finally:
            db.close()

class Selector(Base):
    __tablename__ = "selectors"
    
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, index=True)
    selector = Column(String)
    description = Column(String)
    worked = Column(Boolean, default=True)
