import asyncio
import logging
import requests
from pathlib import Path
from dotenv import dotenv_values
from django.conf import settings

from .models import Service
from .monitor import monitor_services, EnvService

logger = logging.getLogger(__name__)

class ServiceMonitorMiddleware:

    """
    Каждый входящий HTTP-запрос:
     1) Мониторит все Service из БД с enable_monitoring=True
     2) Мониторит все сервисы из .env (как в SystemView)
     3) При смене статуса отправляет уведомления (monitor_services делает это)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        print(">>> ServiceMonitorMiddleware is running for", request.path)
        logger.debug("🛠️  ServiceMonitorMiddleware: incoming %s %s", request.method, request.path)

        # 1) Мониторинг моделей из БД
        db_svcs = Service.objects.all()
        print(f">>> DB services to monitor ({db_svcs.count()}):", [s.name for s in db_svcs])
        try:
            monitor_services(db_svcs)
        except Exception as e:
            print("!!! Error monitoring DB services:", e)
            logger.error("Ошибка мониторинга DB-сервисов: %s", e)

        # 2) Мониторинг сервисов из .env
        env_path = Path(settings.BASE_DIR) / '.env'
        env_services = []
        if env_path.exists():
            config = dotenv_values(env_path)
            svc_names = [val for key, val in config.items() if key.startswith('SERVICE_NAME_') and val]
            print(f">>> Found SERVICE_NAME entries ({len(svc_names)}):", svc_names)
            for nm in svc_names:
                address_key = f'{nm}_HOST'
                port_key = f'{nm}_PORT'
                hostname_key = f'{nm}_HOSTNAME'
                protocol_key = f'{nm}_PROTOCOL'
                address = config.get(address_key)
                port = int(config.get(port_key))
                hostname = config.get(hostname_key)
                protocol = config.get(protocol_key, 'TCP').lower()
                svc = EnvService(name=nm, address=address, port=port, protocol=protocol, hostname=hostname)
                env_services.append(svc)
        print(f">>> ENV services to monitor ({len(env_services)}):", [s.name for s in env_services])
        if env_services:
            try:
                monitor_services(env_services)
            except Exception as e:
                print("!!! Error monitoring ENV services:", e)
                logger.error("Ошибка мониторинга ENV-сервисов: %s", e)

        # продолжаем обработку запроса
        return self.get_response(request)
