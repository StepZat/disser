import asyncio
import logging
import requests
from django.conf import settings
from django.core.cache import cache

from dashboard_app.utils import load_props

logger = logging.getLogger(__name__)
MS_BASE = getattr(settings, "NOTIF_SERVICE_URL", "http://localhost:8003/api")


class EnvService:
    """
    Адаптер для сервисов, описанных в .env:
    хранит атрибуты name, ip, port, protocol, last_is_up и stub-save.
    """
    def __init__(self, name, address, port,hostname, protocol='tcp'):
        self.name         = name
        self.address      = address
        self.port         = port
        self.protocol     = protocol.lower()
        self.hostname     = hostname
        prev_all = cache.get('env_service_statuses', {}) or {}
        self.last_is_up = prev_all.get(self.name, {}).get('is_up')

    def save(self, update_fields=None):
        """
        «Сохраняем» новое значение last_is_up в кэш
        под ключом env_service_statuses.
        """
        statuses = cache.get('env_service_statuses', {}) or {}
        statuses[self.name] = {
            'is_up': self.last_is_up,
            # статус (HTTP code) monitor_services кладёт в svc.status
            'status': getattr(self, 'status', None),
        }
        cache.set('env_service_statuses', statuses, None)


def is_http_up(host, port, timeout=2.0):
    """
    Проверяет HTTP-сервис по корню (/).
    Возвращает (bool up, str статус_код_или_ошибка).
    """
    url = f'http://{host}:{port}/'
    try:
        resp = requests.get(url, timeout=timeout)
        up = 200 <= resp.status_code < 400
        return up, str(resp.status_code)
    except Exception as e:
        return False, str(e)


async def tcp_up(host, port, timeout=3.0):
    """
    Асинхронная проверка TCP-порта.
    Возвращает True, если соединение удалось.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as e:
        logger.debug(f"TCP ping {host}:{port} failed: {e}")
        return False


def send_notifications(svc, now_up):
    """
    Проксирует отправку уведомлений через микросервис.
    Берёт настройки каналов из /properties/.
    """
    print(f"🔔 send_notifications: svc={svc.name} now_up={now_up}")

    # 1) Загружаем (или из кэша) props
    try:
        props = load_props()
    except Exception as e:
        print("‼️ load_props failed:", e)
        props = {}

    print("   → props:", props)

    msg = f"Сервис «{svc.name}» теперь {'UP' if now_up else 'DOWN'}."

    # 2) Email-канал
    if props.get("email_enabled") == "true":
        print("   → email_enabled == true")
        for to in [e for e in props.get("email_recipients", "").split(",") if e]:
            print(f"     → sending EMAIL to {to}")
            payload = {
                "to_email": to,
                "subject":  f"[{svc.name}] статус изменился",
                "body":     msg,
            }
            resp = requests.post(
                f"{MS_BASE}/notify/email/",
                json=payload,
                timeout=5,
                proxies={'http': None, 'https': None}
            )
            print("     ← email response:", resp.status_code, resp.text)
    else:
        print("   → email_enabled != true")

    # 3) Telegram-канал
    print("   → telegram_enabled value:", props.get("telegram_enabled"))
    if props.get("telegram_enabled") == "true":
        print("   → telegram_enabled == true")
        chat_id = props.get("telegram_chat_id")
        print("   → telegram_chat_id is", chat_id)
        if chat_id:
            payload = {"chat_id": chat_id, "message": msg}
            print("     → sending TELEGRAM payload:", payload)
            resp = requests.post(
                f"{MS_BASE}/notify/telegram/",
                json=payload,
                timeout=5,
                proxies={'http': None, 'https': None}
            )
            print("     ← telegram response:", resp.status_code, resp.text)
        else:
            print("   → telegram_chat_id is empty, skip Telegram send")
    else:
        print("   → telegram_enabled != true, skip Telegram send")



def monitor_services(service_objs):
    """
    Единая функция мониторинга для Service-модели и EnvService:
    - service_objs: iterable объектов с атрибутами
      .name, .ip (или address), .port, .protocol, .last_is_up и методом .save().
    - Возвращает список dict: {'svc': svc, 'is_up': bool, 'status': str}.
    - При смене состояния шлёт уведомления и обновляет .last_is_up.
    """
    print(f"🛠️  monitor_services: got {len(service_objs)} services")
    results = []

    for svc in service_objs:
        print(f"🛠️  Checking {svc.name} @ {svc.address}:{svc.port} via {getattr(svc, 'protocol', 'tcp')}")
        logger.debug(svc)
        proto = getattr(svc, 'protocol', 'tcp').lower()
        if proto == 'http':
            up, status = is_http_up(svc.address, svc.port)
            print(f"   📡 HTTP result for {svc.name}: up={up}, status={status}")
        else:
            up = asyncio.run(tcp_up(svc.address, svc.port))
            print(f"   📡 TCP result for {svc.name}: up={up}")
            status = None

        prev = getattr(svc, 'last_is_up', None)
        print(f"   🔄 previous={prev}, current={up}")
        if prev is not None and prev != up:
            send_notifications(svc, up)

        if prev != up:
            svc.last_is_up = up
            try:
                svc.save(update_fields=['last_is_up'])
            except Exception:
                pass

        results.append({'svc': svc, 'is_up': up, 'status': status})

    return results
