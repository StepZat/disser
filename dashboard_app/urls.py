from django.urls import path
from . import views
from .views import (
    ServiceListView,
    ServiceCreateView, ServiceUpdateView, ServiceDeleteView, ServiceStatusAPIView, HostListView, NotificationsView,
    AboutView, SystemView, notifications_test
)

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('services/', ServiceListView.as_view(), name='services'),
    path('services/add/', ServiceCreateView.as_view(), name='service_add'),
    path('services/<int:pk>/edit/', ServiceUpdateView.as_view(), name='service_edit'),
    path('services/<int:pk>/delete/', ServiceDeleteView.as_view(), name='service_delete'),
    path('services/status/',ServiceStatusAPIView.as_view(), name='service_status'),
    path('system/services/',SystemView.as_view(), name='system-services'),
    path('system/hosts/',HostListView.as_view(),    name='system-hosts'),
    path('system/notifications/',NotificationsView.as_view(), name='system-notifications'),
    path('system/about/',AboutView.as_view(),       name='system-about'),
    path('system/notifications/test/', notifications_test, name='system-notifications-test'),

]