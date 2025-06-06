import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timedelta
from logging import INFO
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from dotenv import dotenv_values

from siem_project import settings
from .models import Service, Host
from .forms import ServiceForm, HostForm
from django.contrib.auth.mixins import LoginRequiredMixin
import  requests
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
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
        ctx = super().get_context_data(**kwargs)

        # URL вашего FastAPI
        ctx['API_SCHEME'] = os.environ.get('LOGS_API_SCHEME', 'http')
        ctx['API_HOST']   = os.environ.get('LOGS_API_HOST',   '127.0.0.1')
        ctx['API_PORT']   = os.environ.get('LOGS_API_PORT',   '8081')
        # базовый путь для логов
        ctx['API_PATH']   = '/logs'
        # при необходимости для health и metrics можно завести:
        ctx['HEALTH_PATH']   = '/health'
        ctx['HOSTS_HEALTH_PATH'] = '/hosts/health'
        ctx['METRICS_PATH']  = '/metrics/system'
        # 2) Берём таймзону из .env
        tz_name = os.environ.get('TIME_ZONE', 'UTC')
        tz = ZoneInfo(tz_name)

        # 3) Считаем now и since в этой зоне
        now = datetime.now(tz)
        since = now - timedelta(days=1)

        # 4) Форматируем в ISO без Z (будет локальное время сервера)
        ctx['LOGS_START'] = since.strftime('%Y-%m-%dT%H:%M:%S')
        ctx['LOGS_END'] = now.strftime('%Y-%m-%dT%H:%M:%S')
        return ctx


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

CACHE_KEY = "notif_props"


class NotificationsView(TemplateView):
    template_name = 'dashboard_app/notifications.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # 1) Пытаемся из кэша
        props = cache.get(CACHE_KEY)
        if props is None:
            # 1a) нет — грузим из микросервиса и пишем в кэш
            try:
                props = load_props()
            except Exception:
                props = {}
            cache.set(CACHE_KEY, props, None)

        # 2) Прокидываем в контекст
        for key in KEYS_EMAIL + KEYS_TG:
            ctx[key] = props.get(key, "")
        ctx["email_enabled"]    = props.get("email_enabled", "false")
        ctx["telegram_enabled"] = props.get("telegram_enabled", "false")
        raw = props.get("email_recipients", "")
        ctx["email_recipients"] = [e for e in raw.split(",") if e]
        return ctx

    def post(self, request, *args, **kwargs):
        session = requests.Session()
        session.trust_env = False

        # 1) Сброс Email
        if "reset_email" in request.POST:
            email_keys = ["email_enabled"] + KEYS_EMAIL + ["email_recipients"]
            errors = []
            for key in email_keys:
                resp = session.delete(f"{MS_BASE}/properties/{key}/", timeout=5)
                if resp.status_code not in (204, 404):
                    errors.append(key)
            # чистим только Email-поля из кэша
            props = cache.get(CACHE_KEY, {}) or {}
            for key in email_keys:
                props.pop(key, None)
            cache.set(CACHE_KEY, props, None)

            if errors:
                messages.error(request, _("Ошибка сброса Email: ") + ", ".join(errors))
            else:
                messages.success(request, _("Настройки Email сброшены"))
            return redirect('system-notifications')

        # 2) Сброс Telegram
        if "reset_telegram" in request.POST:
            tg_keys = ["telegram_enabled", "telegram_token", "telegram_chat_id"]
            errors = []
            for key in tg_keys:
                resp = session.delete(f"{MS_BASE}/properties/{key}/", timeout=5)
                if resp.status_code not in (204, 404):
                    errors.append(key)
            props = cache.get(CACHE_KEY, {}) or {}
            for key in tg_keys:
                props.pop(key, None)
            cache.set(CACHE_KEY, props, None)

            if errors:
                messages.error(request, _("Ошибка сброса Telegram: ") + ", ".join(errors))
            else:
                messages.success(request, _("Настройки Telegram сброшены"))
            return redirect('system-notifications')

        # 3) Сохранение Email или Telegram
        form_type = request.POST.get("form_type")
        errors = []

        # 3a) Email
        if form_type == "email":
            # флаг включения
            enabled = "true" if request.POST.get("email_enabled") == "on" else "false"
            resp = session.patch(f"{MS_BASE}/properties/email_enabled/", json={"value": enabled}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/",
                                    json={"key":"email_enabled","value":enabled}, timeout=5)
            if not resp.ok:
                errors.append("email_enabled")

            # SMTP-поля
            for key in KEYS_EMAIL:
                val = request.POST.get(key, "")
                resp = session.patch(f"{MS_BASE}/properties/{key}/", json={"value": val}, timeout=5)
                if resp.status_code == 404:
                    resp = session.post(f"{MS_BASE}/properties/",
                                        json={"key":key,"value":val}, timeout=5)
                if not resp.ok:
                    errors.append(key)

            # получатели
            recips = request.POST.getlist("email_recipients[]")
            recips_val = ",".join(r for r in recips if r)
            resp = session.patch(f"{MS_BASE}/properties/email_recipients/", json={"value": recips_val}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/",
                                    json={"key":"email_recipients","value":recips_val}, timeout=5)
            if not resp.ok:
                errors.append("email_recipients")

            if not errors:
                # обновляем только Email-поля в кэше
                props = cache.get(CACHE_KEY, {}) or {}
                props.update({
                    "email_enabled": enabled,
                    **{k: request.POST.get(k, "") for k in KEYS_EMAIL},
                    "email_recipients": recips_val,
                })
                cache.set(CACHE_KEY, props, None)
                messages.success(request, _("Параметры Email успешно сохранены"))
            else:
                messages.error(request, _("Ошибка сохранения Email: ") + ", ".join(errors))

        # 3b) Telegram
        elif form_type == "telegram":
            enabled = "true" if request.POST.get("telegram_enabled") == "on" else "false"
            resp = session.patch(f"{MS_BASE}/properties/telegram_enabled/", json={"value": enabled}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/",
                                    json={"key":"telegram_enabled","value":enabled}, timeout=5)
            if not resp.ok:
                errors.append("telegram_enabled")

            token = request.POST.get("telegram_token", "")
            resp = session.patch(f"{MS_BASE}/properties/telegram_token/", json={"value": token}, timeout=5)
            if resp.status_code == 404:
                resp = session.post(f"{MS_BASE}/properties/",
                                    json={"key":"telegram_token","value":token}, timeout=5)
            if not resp.ok:
                errors.append("telegram_token")

            chat_id = request.POST.get("telegram_chat_id", "")
            resp = session.patch(f"{MS_BASE}/properties/telegram_chat_id/", json={"value": chat_id}, timeout=5)
            if resp.status_code in (404, 405):
                resp = session.post(f"{MS_BASE}/properties/",
                                    json={"key":"telegram_chat_id","value":chat_id}, timeout=5)
            if not resp.ok:
                errors.append("telegram_chat_id")

            if not errors:
                props = cache.get(CACHE_KEY, {}) or {}
                props.update({
                    "telegram_enabled": enabled,
                    "telegram_token":   token,
                    "telegram_chat_id": chat_id,
                })
                cache.set(CACHE_KEY, props, None)
                messages.success(request, _("Параметры Telegram успешно сохранены"))
            else:
                messages.error(request, _("Ошибка сохранения Telegram: ") + ", ".join(errors))

        else:
            messages.error(request, _("Неизвестная форма уведомлений"))

        return redirect('system-notifications')


class HostListView(TemplateView):
    template_name = 'dashboard_app/hosts.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hosts = Host.objects.all()
        ctx['hosts']     = hosts
        ctx['host_form'] = HostForm()

        # 1) текущий хост
        sel = self.request.GET.get('host')
        ctx['current_host'] = (
            hosts.filter(pk=sel).first()
            if sel else
            (hosts.first() if hosts.exists() else None)
        )

        # 2) парсим start/end из GET или задаём по-умолчанию последние час
        fmt = '%Y-%m-%dT%H:%M'
        now = timezone.localtime()
        # начало
        start_str = self.request.GET.get('start')
        try:
            start_dt = datetime.strptime(start_str, fmt) if start_str else now - timedelta(hours=1)
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        except Exception:
            start_dt = now - timedelta(hours=1)
            start_str = start_dt.strftime(fmt)
        # конец
        end_str = self.request.GET.get('end')
        try:
            end_dt = datetime.strptime(end_str, fmt) if end_str else now
            end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())
        except Exception:
            end_dt = now
            end_str = end_dt.strftime(fmt)

        # epoch в миллисекундах
        ctx['from_ts'] = int(start_dt.timestamp() * 1000)
        ctx['to_ts']   = int(end_dt.timestamp()   * 1000)
        # для заполнения формы
        ctx['start_str'] = start_str or start_dt.strftime(fmt)
        ctx['end_str']   = end_str   or end_dt.strftime(fmt)

        # 3) грузим JSON-дэшборд и группы панелей
        path = Path(settings.BASE_DIR) / 'grafana' / 'provisioning' / 'dashboards' /'1860_rev34.json'
        with path.open(encoding='utf-8') as fp:
            dash = json.load(fp)

        groups = []
        current = None
        for p in dash.get('panels', []):
            if p.get('type') == 'row':
                if current:
                    groups.append(current)
                current = {
                    'title': p.get('title', 'Без названия'),
                    'panels': [c for c in p.get('panels', []) if c.get('id') is not None]
                }
            else:
                # старый формат: некоторые панели могут быть на верхнем уровне
                if current and p.get('id') is not None:
                    current['panels'].append(p)
        if current:
            groups.append(current)

        ctx['dashboard_groups'] = groups
        ctx['grafana_base']    = settings.GRAFANA_BASE.rstrip('/')
        ctx['dashboard_uid']   = dash.get('uid') or dash.get('id')
        ctx['time_zone']       = settings.TIME_ZONE
        ping_statuses = cache.get('hosts_ping_statuses', {})
        # добавим в каждый объект хоста атрибуты, чтобы шаблон мог их вывести
        for h in ctx['hosts']:
            st = ping_statuses.get(h.pk, {})
            h.ping_up = st.get('up')
        return ctx

    def post(self, request, *args, **kwargs):
        # Добавить хост
        if 'add_host' in request.POST:
            form = HostForm(request.POST)
            if form.is_valid():
                form.save()
            return redirect(f"{request.path}?host=")

        # Удалить хост
        if 'delete_host' in request.POST:
            Host.objects.filter(pk=request.POST['delete_host']).delete()
            return redirect(f"{request.path}?host=")

        return super().get(request, *args, **kwargs)

class AboutView(TemplateView):
    template_name = 'dashboard_app/about.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # существующий код по services, hosts и т.п.
        # ...

        # ——— Блок «О системе» ———
        ctx['system_info'] = {
            'app_name': settings.APP_NAME,
            'version': settings.APP_VERSION,
            'build_date': settings.APP_BUILD_DATE,
            'authors': settings.APP_AUTHORS,
            'license': settings.APP_LICENSE,
            'repo_url': settings.APP_REPO_URL,
        }

        return ctx

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

DASHBOARD_JSON_PATH = settings.BASE_DIR / "dashboard_app" / "static" / "dashboards" / "1860_rev40.json"

def hosts_view(request):
    # добавление нового хоста
    if request.method == "POST" and "add_host" in request.POST:
        form = HostForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("hosts"))
    else:
        form = HostForm()

    # удаление
    if request.method == "POST" and "delete_host" in request.POST:
        h = get_object_or_404(Host, pk=request.POST.get("delete_host"))
        h.delete()
        return redirect(reverse("hosts"))

    # выбор текущего хоста
    hosts = Host.objects.all()
    sel = request.GET.get("host")
    current = hosts.filter(pk=sel).first() if sel else None

    # загрузим JSON дашборда и вытянем список panelId
    with open(DASHBOARD_JSON_PATH, encoding="utf-8") as f:
        dash = json.load(f)
    panel_ids = [p["id"] for p in dash["panels"] if p.get("type") != "row"]

    return render(request, "dashboard_app/hosts.html", {
        "hosts": hosts,
        "form": form,
        "current": current,
        "panel_ids": panel_ids,
        # ваша базовая ссылка на Grafana (замените на свою)
        "grafana_base": "http://127.0.0.1:3000/d-solo/1860/node-exporter-full?orgId=1",
    })

class EventsView(TemplateView):
    """
    Отображает страницу событий.
    Данные подтягиваются на фронте через fetch('/logs').
    """
    template_name = "dashboard_app/events.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['API_SCHEME'] = os.environ.get('LOGS_API_SCHEME', 'http')
        context['API_HOST'] = os.environ.get('LOGS_API_HOST', '127.0.0.1')
        context['API_PORT'] = os.environ.get('LOGS_API_PORT', '8081')
        context['API_PATH'] = os.environ.get('LOGS_API_PATH', '/logs')
        # 1. Собираем все параметры фильтрации/пагинации из GET
        params = {
            "count": self.request.GET.get("count", 10),
            "skip": self.request.GET.get("skip", 0),
            "type": self.request.GET.get("type", "all"),
        }
        for key in ("log_level", "hostname", "search", "start", "end"):
            if self.request.GET.get(key):
                params[key] = self.request.GET[key]

        # 2. Запрашиваем JSON у FastAPI
        url = f"{settings.LOGS_API_BASE_URL}"
        resp = requests.get(url, params=params, proxies={'http': None, 'https': None})
        resp.raise_for_status()
        payload = resp.json()

        # 3. Вытаскиваем список логов из payload['data']
        logs = payload.get("data", [])

        # 4. Кладём их в контекст
        context["logs"] = logs
        context["total"] = payload.get("total", 0)
        return context
