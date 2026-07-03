from celery import shared_task
from loguru import logger

@shared_task
def debug_task():
    logger.info("Celery shared debug task is running successfully!")
    return "success"
