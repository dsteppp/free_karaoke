from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "karaoke.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Track(Base):
    __tablename__ = "tracks"

    id               = Column(String,  primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    filename         = Column(String,  unique=True, index=True, nullable=False)
    original_name    = Column(String,  nullable=False)

    title            = Column(String,  index=True, nullable=True)
    artist           = Column(String,  index=True, nullable=True)

    original_path    = Column(String,  nullable=True)
    vocals_path      = Column(String,  nullable=True)
    instrumental_path= Column(String,  nullable=True)
    lyrics_path      = Column(String,  nullable=True)
    karaoke_json_path= Column(String,  nullable=True)

    duration_sec     = Column(Integer, default=0)
    status           = Column(String,  default="pending")
    offset           = Column(Float,   default=0.0)
    error_message    = Column(String,  nullable=True)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()