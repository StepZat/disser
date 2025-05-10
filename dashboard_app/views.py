import asyncio
import json
import logging
import socket
from logging import INFO
from pathlib import Path

from django.core.cache import cache
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
from .monitor import monitor_services, EnvService
from .utils import load_props

logger = logging.getLogger(__name__)

MS_BASE = getattr(settings, "NOTIF_SERVICE_URL", "http://localhost:8003/api")

KEYS_EMAIL = [
    "smtp_server", "smtp_port", "smtp_user",
    "smtp_password", "smtp_timeout", "smtp_security"
]
KEYS_TG = ["telegram_token", 'telegram_chat_id']

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

    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     # получаем все модели Service
    #     qs = Service.objects.all()
    #     monitored = monitor_services(qs)
    #     # приводим к списку словарей для шаблона
    #     context['services'] = [
    #          {
    #             'name': item['svc'].name,
    #             'hostname': item['svc'].hostname,
    #             'address': item['svc'].address,
    #             'port': item['svc'].port,
    #             'is_up': item['is_up'],
    #             'status': item['status'],
    #          }
    #         for item in monitored
    #         ]
    #     return context

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

def send_status_change(svc, now_up):
    """
    Отправляет уведомление в зависимости от включённых каналов.
    """
    # 1) Получаем все свойства уведомлений
    r = requests.get(f"{MS_BASE}/properties/", timeout=2, proxies={'http': None, 'https': None})
    r.raise_for_status()
    props = {p['key']: p['value'] for p in r.json()}

    message = f"Сервис «{svc.name}» теперь {'UP' if now_up else 'DOWN'}."
    # Email-канал
    if props.get("email_enabled") == "true":
        # список получателей CSV
        recips = [e for e in props.get("email_recipients", "").split(",") if e]
        for to in recips:
            payload = {
                "to_email": to,
                "subject": f"[{svc.name}] статус изменился",
                "body": message
            }
            requests.post(f"{MS_BASE}/notify/email/", json=payload, timeout=5)

    # Telegram-канал
    if props.get("telegram_enabled") == "true":
        # Храните Chat ID в свойстве, например telegram_chat_id
        chat_id = props.get("telegram_chat_id", "")
        if chat_id:
            payload = {"chat_id": chat_id, "message": message}
            requests.post(f"{MS_BASE}/notify/telegram/", json=payload, timeout=5)

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
            return True
        else:
            return False
    except Exception as e:
        logger.debug(f"[DEBUG] {url} → exception: {e}")
        return False, str(e)

class SystemView(TemplateView):
    model = Service
    template_name = 'dashboard_app/system.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # читаем .env
        env_path = Path(settings.BASE_DIR) / '.env'
        services = []
        if env_path.exists():
            config = dotenv_values(env_path)
            # чем-то вроде:
            names = [v for k,v in config.items() if k.startswith('SERVICE_NAME_')]
            for nm in names:
                host = config.get(f'{nm}_HOST')
                port = int(config.get(f'{nm}_PORT', 0) or 0)
                protocol = config.get(f'{nm}_PROTOCOL', 'tcp').lower()
                hostname = config.get(f'{nm}_HOSTNAME')
                services.append({
                    'name': nm,
                    'hostname': hostname,
                    'address': host,
                    'port': port,
                    'protocol': protocol,
                    # для статуса иконки Up/Down можно не передавать,
                    # т.к. мониторинг теперь в middleware
                    'is_up': None,
                    'status': None,
                })
        # 2) Подтягиваем последние сохранённые статусы
        env_statuses = cache.get("env_service_statuses", {})
        print(env_statuses)
        # 3) Заполняем
        for svc in services:
            st = env_statuses.get(svc['name'])
            print(st)
            if st:
                svc['is_up'] = st['is_up']
                svc['status'] = st['status']

        ctx['services'] = services
        return ctx

class NotificationsView(TemplateView):
    template_name = 'dashboard_app/notifications.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            props = load_props()
        except Exception:
            props = {}

        # fill in all fields, including enabled flags
        for key in KEYS_EMAIL + KEYS_TG:
            ctx[key] = props.get(key, "")
        ctx["email_enabled"]    = props.get("email_enabled", "false")
        ctx["telegram_enabled"] = props.get("telegram_enabled", "false")
        raw = props.get("email_recipients", "")
        ctx["email_recipients"] = [e for e in raw.split(",") if e]
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
                if not errors:
                    from django.core.cache import cache
                    cache.delete("notif_props")

            recips = request.POST.getlist("email_recipients[]")
            recips_val = ",".join([r for r in recips if r])
            resp = session.patch(f"{MS_BASE}/properties/email_recipients/", json={"value": recips_val}, timeout=2)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/", json={"key": "email_recipients", "value": recips_val},
                                    timeout=2)
            if not resp.ok: errors.append("email_recipients")
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

            key = "telegram_chat_id"
            chat_id = request.POST.get(key, "")
            url = f"{MS_BASE}/properties/{key}/"
            print(f"→ PATCH {url} payload={{'value': {chat_id!r}}}")
            resp = session.patch(url, json={"value": chat_id}, timeout=5)
            print(f"← {resp.status_code} {resp.text}")
            if resp.status_code in (404, 405):
                post_url = f"{MS_BASE}/properties/"
                print(f"→ POST {post_url} payload={{'key': {key!r}, 'value': {chat_id!r}}}")
                resp = session.post(post_url, json={"key": key, "value": chat_id}, timeout=5)
                print(f"← {resp.status_code} {resp.text}")
            if not resp.ok:
                errors.append(key)

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

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error("notifications_test: неверный JSON: %r", request.body)
        return HttpResponseBadRequest("Invalid JSON")

    logger.debug("notifications_test: received payload %r", data)

    channel = data.get('channel')
    to      = data.get('to')
    session = requests.Session()
    session.trust_env = False

    if channel == 'email':
        endpoint = f"{MS_BASE}/notify/email/"
        # вот что нужно передавать
        payload  = {
            "to_email": to,
            "subject":  "Тестовое сообщение",
            "body":     "Это тестовое сообщение для проверки работы email-канала."
        }
    elif channel == 'telegram':
        endpoint = f"{MS_BASE}/notify/telegram/"
        payload  = {
            "chat_id": to,
            "message": "Это тестовое сообщение для проверки работы Telegram-канала."
        }
    else:
        logger.error("notifications_test: unknown channel %r", channel)
        return HttpResponseBadRequest('Unknown channel')

    logger.debug("notifications_test: POST %s with %r", endpoint, payload)
    resp = session.post(endpoint, json=payload, timeout=5)
    logger.debug("notifications_test: response %s %r", resp.status_code, resp.text)

    return JsonResponse({}, status=(200 if resp.ok else resp.status_code))
