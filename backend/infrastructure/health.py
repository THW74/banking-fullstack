import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from sqlalchemy import text

from .config import settings
from .database import engine
from .celery import celery_app
from .logging import get_logger

logger = get_logger()


class HealthCheck:
    def __init__(self):
        self._cache_duration = timedelta(seconds=20)
        self._cached_status: Optional[Dict[str, Any]] = None
        self._last_check_time: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def check_database(self) -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def check_redis(self) -> bool:
        try:
            redis_client = celery_app.backend.client
            redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def check_broker(self) -> bool:
        try:
            conn = celery_app.connection()
            try:
                conn.ensure_connection(max_retries=2)
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Broker/RabbitMQ health check failed: {e}")
            return False

    async def run_checks(self) -> Dict[str, Any]:
        current_time = datetime.now(timezone.utc)
        
        async with self._lock:
            if (
                self._cached_status is not None
                and self._last_check_time is not None
                and (current_time - self._last_check_time) < self._cache_duration
            ):
                return self._cached_status

        try:
            async with asyncio.timeout(5.0):
                db_ok, redis_ok, broker_ok = await asyncio.gather(
                    self.check_database(),
                    self.check_redis(),
                    self.check_broker()
                )
        except asyncio.TimeoutError:
            db_ok = redis_ok = broker_ok = False

        status = "healthy" if (db_ok and redis_ok and broker_ok) else "unhealthy"
        
        health_status = {
            "status": status,
            "timestamp": current_time.isoformat(),
            "services": {
                "database": "healthy" if db_ok else "unhealthy",
                "redis": "healthy" if redis_ok else "unhealthy",
                "broker": "healthy" if broker_ok else "unhealthy",
            }
        }

        async with self._lock:
            self._cached_status = health_status
            self._last_check_time = current_time

        return health_status


health_checker = HealthCheck()
