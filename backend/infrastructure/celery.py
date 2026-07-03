from celery import Celery
from .config import settings

celery_app = Celery(
    "banking",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    redbeat_redis_url=settings.CELERY_RESULT_BACKEND,
)

# Auto-discover tasks from files named tasks.py inside any specified packages
celery_app.autodiscover_tasks(
    [
        "infrastructure",
        # Add future modules here to scan their tasks.py files:
        # "modules.users",
        # "modules.auth",
    ],
    force=True,
)
