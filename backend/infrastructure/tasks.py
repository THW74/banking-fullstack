from celery import shared_task
from loguru import logger

@shared_task
def debug_task():
    logger.info("Celery shared debug task is running successfully!")
    return "success"


@shared_task
def send_otp_email_task(email: str, otp: str):
    import smtplib
    from email.mime.text import MIMEText
    from infrastructure.config import settings

    logger.info(f"Sending OTP email task initiated for {email}")
    msg = MIMEText(f"Your banking app verification code is: {otp}\nIt is valid for 5 minutes.")
    msg["Subject"] = "Your Verification Code"
    msg["From"] = "noreply@teknollbank.com"
    msg["To"] = email

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"OTP email sent successfully to {email}")
        return "sent"
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {e}")
        return "failed"
