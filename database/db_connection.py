# database/db_connection.py
import pymysql
from dbutils.pooled_db import PooledDB
from config import Config

_pool: PooledDB | None = None


def _get_pool() -> PooledDB:
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,
            mincached=2,
            maxcached=10,
            maxconnections=20,
            blocking=True,
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            db=Config.MYSQL_DB,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
        )
    return _pool


def get_db_connection():
    """풀에서 커넥션을 꺼내 반환. conn.close() 시 풀에 반환됨."""
    return _get_pool().connection()
