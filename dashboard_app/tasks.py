# dashboard_app/tasks.py

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from dotenv import dotenv_values
from celery import shared_task

from .models import Service, Host
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

@shared_task
def ping_all_hosts():
    """
    Пингуем все хосты из БД, сохраняем в модель и в Redis-кэш.
    """
    hosts = Host.objects.all()
    statuses = {}  # для кэша

    for h in hosts:
        # запускаем команду ping — 1 пакет, таймаут 1 сек
        cmd = f"ping -n 1 -w 1000 {h.address}" if os.name=='nt' else f"ping -c1 -W1 {h.address}"
        proc = subprocess.run(shlex.split(cmd),
                              capture_output=True, text=True)
        up = proc.returncode == 0

        # сохраняем в модель
        h.is_up = up
        h.save(update_fields=['is_up'])

        # готовим кэш: { host_pk: {'up': bool, 'latency': float } }
        statuses[h.pk] = {'up': up}

    # сохраняем в Redis без истечения
    cache.set('hosts_ping_statuses', statuses, None)
