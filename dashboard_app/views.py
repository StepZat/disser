import asyncio

from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import Service
from .forms import ServiceForm
from django.contrib.auth.mixins import LoginRequiredMixin
import  requests

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


class SystemView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard_app/system.html'