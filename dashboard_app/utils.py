# dashboard_app/utils.py
from django.core.cache import cache
import requests
from django.conf import settings

MS_BASE = getattr(settings, "NOTIF_SERVICE_URL", "http://localhost:8003/api")

def load_props():
    props = cache.get("notif_props")
    if props is None:
        try:
            resp = requests.get(
                f"{MS_BASE}/properties/",
                timeout=2,
                # если у вас прокси в окружении — отключим их
                proxies={'http': None, 'https': None},
            )
            resp.raise_for_status()
            props = {p["key"]: p["value"] for p in resp.json()}
            print("✅ load_props fetched:", props)
            cache.set("notif_props", props, 300)
        except Exception as e:
            print("‼️ load_props ERROR fetching properties:", e)
            # не кэшируем пустой словарь, чтобы не зависнуть навсегда
            return {}
    else:
        print("🗄️ load_props from cache:", props)
    return props
