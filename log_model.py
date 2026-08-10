
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String
from db import Base


class DropLogInfoModel(Base):
    __tablename__ = "drop_log_info"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False, unique=True)
    folder_name = Column(String(512), nullable=False)
    status = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now())
    updated_at = Column(DateTime, default=datetime.now(), onupdate=datetime.now())
