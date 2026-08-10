from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from config import settings
def get_engine():
    engine = create_engine(settings.MSSQL_CONNECTION_ODBC,fast_executemany=True, isolation_level="READ COMMITTED",
                pool_size=3,
                pool_timeout=30,
                pool_recycle=7200,
                pool_pre_ping=True,   # test connection before using from pool
            )
    return engine

def get_db_connection():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return SessionLocal()


def get_engine_mysql():
    engine = create_engine(settings.MYSQL_CONNECTION_STRING,
                pool_size=5,
                pool_timeout=settings.POOL_TIMEOUT,
                pool_recycle=settings.POOL_RECYCLE,
                pool_pre_ping=True,   # test connection before using from pool
            )
    return engine

def get_db_connection_mysql():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine_mysql())
    return SessionLocal()

Base = declarative_base()