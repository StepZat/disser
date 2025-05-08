import asyncio
import json
import logging
import socket
from logging import INFO
from pathlib import Path

from django.http import JsonResponse, HttpResponseBadRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from dotenv import dotenv_values

from siem_project import settings
from .models import Service
from .forms import ServiceForm
from django.contrib.auth.mixins import LoginRequiredMixin
import  requests
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.translation import gettext as _
logger = logging.getLogger(__name__)

MS_BASE = getattr(settings, "NOTIF_SERVICE_URL", "http://localhost:8003/api")

KEYS_EMAIL = [
    "smtp_server", "smtp_port", "smtp_user",
    "smtp_password", "smtp_timeout", "smtp_security"
]
KEYS_TG = ["telegram_token"]

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard_app/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Загрузка логов из внешнего API MongoDB
        try:
            # Адрес и порт API берутся из переменных окружения
            import os
            api_host = os.environ.get('LOGS_API_HOST', '127.0.0.1')
            api_port = os.environ.get('LOGS_API_PORT', '8081')
            api_scheme = os.environ.get('LOGS_API_SCHEME', 'http')
            api_path = os.environ.get('LOGS_API_PATH', '/logs')
            api_url = f"{api_scheme}://{api_host}:{api_port}{api_path}"
            params = {'count': 20, 'type': 'dangerous'}
            print("API URL:", api_url)
            response = requests.get(
                                    api_url,
                                    params=params,
                                    timeout=5,
                                    proxies={'http': None, 'https': None})
            response.raise_for_status()
            # Получаем список словарей
            logs_list = response.json()
            # Убираем лишние кавычки вокруг поля @timestamp
            for log in logs_list:
                ts = log.get('@timestamp')
                if isinstance(ts, str):
                    log['@timestamp'] = ts.strip('"')
            context['logs'] = logs_list
        except requests.RequestException as e:
            # В случае ошибки передаём пустой список и сообщение об ошибке
            context['logs'] = []
            context['logs_error'] = str(e)
        return context

class ServiceListView(LoginRequiredMixin, ListView):
    model = Service
    template_name = 'dashboard_app/services.html'
    context_object_name = 'services'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        term = self.request.GET.get('filter', '')
        if term:
            qs = qs.filter(name__icontains=term)
        return qs

    def post(self, request, *args, **kwargs):
        # Собираем все выбранные ID из чекбоксов
        ids = request.POST.getlist('selected_pk')
        if ids:
            Service.objects.filter(pk__in=ids).delete()
        return redirect('services')

    def get_context_data(self, **kwargs):
        context  = super().get_context_data(**kwargs)
        services = list(context['services'])

        async def check_service(svc):
            try:
                # пытаемся TCP-соединение
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(svc.address, svc.port),
                    timeout=3
                )
                w.close(); await w.wait_closed()
                return True
            except:
                return False

        async def monitor_all(svcs):
            return await asyncio.gather(*(check_service(s) for s in svcs))

        # запускаем весь мониторинг
        statuses = asyncio.run(monitor_all(services))
        print("[DEBUG] Service statuses:", [(svc.address, svc.port, up) for svc, up in zip(services, statuses)])

        # прикрепляем динамический атрибут
        for svc, is_up in zip(services, statuses):
            svc.is_up = is_up

        context['services'] = services
        return context

class ServiceCreateView(LoginRequiredMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = 'dashboard_app/service_form.html'
    success_url = reverse_lazy('services')

class ServiceUpdateView(LoginRequiredMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    template_name = 'dashboard_app/service_form.html'
    success_url = reverse_lazy('services')

class ServiceDeleteView(LoginRequiredMixin, DeleteView):
    model = Service
    template_name = 'dashboard_app/service_confirm_delete.html'
    success_url = reverse_lazy('services')

class ServiceStatusAPIView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        # Берём все сервисы из БД
        services = Service.objects.all()
        data = []
        # Синхронная проверка через socket вместо asyncio
        import socket
        for svc in services:
            is_up = False
            try:
                with socket.create_connection((svc.address, svc.port), timeout=3):
                    is_up = True
            except Exception:
                is_up = False
            data.append({'pk': svc.pk, 'is_up': is_up})
        return JsonResponse(data, safe=False)


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception as e:
        logger.debug(f"TCP ping failed {host}:{port} — {e}")
        return False

def is_http_up(host: str, port: int, scheme: str = 'http', path: str = '/', timeout: float = 2.0) -> (bool, str):
    """Возвращает (статус, текст ошибки или статус-кода)."""
    url = f'{scheme}://{host}:{port}{path}'
    logger.debug(f"[DEBUG] HTTP ping → {url}")
    try:
        resp = requests.get(url, timeout=timeout)
        logger.debug(f"[DEBUG] {url} → {resp.status_code}")
        # считаем up только 2xx и 3xx
        if 200 <= resp.status_code < 400:
            return True, str(resp.status_code)
        else:
            return False, str(resp.status_code)
    except Exception as e:
        logger.debug(f"[DEBUG] {url} → exception: {e}")
        return False, str(e)

class SystemView(TemplateView):
    template_name = 'dashboard_app/system.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        env_path = Path(settings.BASE_DIR) / '.env'
        services = []

        if env_path.exists():
            config = dotenv_values(env_path)

            # Собираем уникальные имена сервисов из SERVICE_NAME_*
            seen = set()
            names = [
                val for key, val in config.items()
                if key.startswith('SERVICE_NAME_') and val and val not in seen and not seen.add(val)
            ]

            for name in names:
                prefix   = name.upper()
                host     = config.get(f'{prefix}_HOST', '')
                port_str = config.get(f'{prefix}_PORT', '')
                hostname = config.get(f'{prefix}_HOSTNAME', '')
                path     = config.get(f'{prefix}_PATH', '/')
                proto    = config.get(f'{prefix}_PROTOCOL', 'tcp').lower()

                # Приводим порт к целому
                try:
                    port = int(port_str)
                except (TypeError, ValueError):
                    port = None

                # Выбираем, как пинговать
                is_up = False
                if host and port:
                    if proto == 'http':
                        is_up = is_http_up(host, port, 'http', path)
                    else:
                        is_up = is_port_open(host, port)

                services.append({
                    'name':     name,
                    'hostname': hostname,
                    'ip':       host,
                    'port':     port_str,
                    'is_up':    is_up,
                })

        ctx['services'] = services
        return ctx

class NotificationsView(TemplateView):
    template_name = 'dashboard_app/notifications.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            r = requests.get(f"{MS_BASE}/properties/", timeout=3, proxies={'http': None, 'https': None})
            import sys;print(r.json(), file=sys.stderr)
            r.raise_for_status()
            props = {p["key"]: p["value"] for p in r.json()}
        except Exception:
            props = {}

        # fill in all fields, including enabled flags
        for key in KEYS_EMAIL + KEYS_TG:
            ctx[key] = props.get(key, "")
        ctx["email_enabled"]    = props.get("email_enabled", "false")
        ctx["telegram_enabled"] = props.get("telegram_enabled", "false")
        return ctx

    def post(self, request, *args, **kwargs):
        form = request.POST.get("form_type")
        session = requests.Session()
        session.trust_env = False
        errors = []

        if form == "email":
            # --- Email block ---
            enabled = "true" if request.POST.get("email_enabled") == "on" else "false"
            resp = session.patch(f"{MS_BASE}/properties/email_enabled/", json={"value": enabled}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/", json={"key":"email_enabled","value":enabled}, timeout=5)
            if not resp.ok:
                errors.append("email_enabled")

            for key in KEYS_EMAIL:
                val = request.POST.get(key, "")
                resp = session.patch(f"{MS_BASE}/properties/{key}/", json={"value": val}, timeout=5)
                if resp.status_code == 404:
                    resp = session.post(f"{MS_BASE}/properties/", json={"key":key,"value":val}, timeout=5)
                if not resp.ok:
                    errors.append(key)

            if errors:
                messages.error(request, _("Ошибка сохранения Email: ") + ", ".join(errors))
            else:
                messages.success(request, _("Параметры Email успешно сохранены"))

        elif form == "telegram":
            # --- Telegram block ---
            enabled = "true" if request.POST.get("telegram_enabled") == "on" else "false"
            resp = session.patch(f"{MS_BASE}/properties/telegram_enabled/", json={"value": enabled}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/", json={"key":"telegram_enabled","value":enabled}, timeout=5)
            if not resp.ok:
                errors.append("telegram_enabled")

            token = request.POST.get("telegram_token", "")
            resp = session.patch(f"{MS_BASE}/properties/telegram_token/", json={"value": token}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/", json={"key":"telegram_token","value":token}, timeout=5)
            if not resp.ok:
                errors.append("telegram_token")

            if errors:
                messages.error(request, _("Ошибка сохранения Telegram: ") + ", ".join(errors))
            else:
                messages.success(request, _("Параметры Telegram успешно сохранены"))
        else:
            messages.error(request, _("Неизвестная форма уведомлений"))

        return redirect('system-notifications')

class HostListView(TemplateView):
    template_name = 'dashboard_app/hosts.html'

class AboutView(TemplateView):
    template_name = 'dashboard_app/about.html'

@csrf_exempt
def notifications_test(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('Bad method')
    data = json.loads(request.body)
    channel = data.get('channel')
    to      = data.get('to')
    if channel == 'email':
        endpoint = f"{MS_BASE}/notify/email/"
        payload  = {'to': to}
    elif channel == 'telegram':
        endpoint = f"{MS_BASE}/notify/telegram/"
        payload  = {'to': to}
    else:
        return HttpResponseBadRequest('Unknown channel')
    r = requests.post(endpoint, json=payload, timeout=5)
    return JsonResponse({}, status=(200 if r.ok else 500))

