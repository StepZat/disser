# app/apps.py
import sys
from django.apps import AppConfig

class AppConfigNotifications(AppConfig):
    name = "app"                 # точно как в INSTALLED_APPS
    verbose_name = "Notifications Service"

    def ready(self):
        # если мы делаем makemigrations или migrate — пропускаем загрузку из БД
        if any(cmd in sys.argv for cmd in ("makemigrations", "migrate")):
            return

        from .config import NotificationConfig
        NotificationConfig.load()
