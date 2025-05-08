# app/notifications.py

import ssl
import smtplib
from email.message import EmailMessage
from telegram import Bot
from .config import NotificationConfig, ConfigError

def send_email(to_email: str, subject: str, body: str):
    # Берём настройки из памяти
    server   = NotificationConfig.get("smtp_server")
    port     = int(NotificationConfig.get("smtp_port"))
    user     = NotificationConfig.get("smtp_user")
    pwd      = NotificationConfig.get("smtp_password")
    timeout  = int(NotificationConfig.get("smtp_timeout"))
    security = NotificationConfig.get("smtp_security")  # none/ssl/starttls

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to_email
    msg.set_content(body)

    if security == "ssl":
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(server, port, context=ctx, timeout=timeout) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(server, port, timeout=timeout) as smtp:
            if security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, pwd)
            smtp.send_message(msg)

def send_telegram(chat_id: str, text: str):
    token = NotificationConfig.get("telegram_token")
    bot = Bot(token=token)
    bot.send_message(chat_id=chat_id, text=text)
