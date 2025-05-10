# dashboard_app/tasks.py

import asyncio
from pathlib import Path
from django.conf import settings
from dotenv import dotenv_values
from celery import shared_task

from .models import Service
from .monitor import monitor_services, EnvService

@shared_task
def monitor_all_services():
    """
    Единый мониторинг для:
     – всех DB-сервисов (enable_monitoring=True)
     – всех .env-сервисов
    """
    # 1) Собираем модели Django
    db_svcs = list(Service.objects.all())

    # 2) Собираем .env-сервисы
    env_path = Path(settings.BASE_DIR) / '.env'
    env_svcs = []
    if env_path.exists():
        cfg = dotenv_values(env_path)
        names = [v for k, v in cfg.items() if k.startswith('SERVICE_NAME_') and v]
        for nm in names:
            host = cfg.get(f"{nm}_HOST")
            if not host:
                continue
            try:
                port = int(cfg.get(f"{nm}_PORT", 0) or 0)
            except ValueError:
                port = 0
            proto = cfg.get(f"{nm}_PROTOCOL", 'tcp').lower()
            hostname = cfg.get(f"{nm}_HOSTNAME")
            # hostname можно брать из HOSTNAME, но monitor_services сейчас не выводит его
            env_svcs.append(EnvService(name=nm, address=host, port=port, protocol=proto, hostname=hostname))

    # 3) Запускаем единый цикл мониторинга
    all_services = db_svcs + env_svcs
    monitor_services(all_services)
