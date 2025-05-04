from django.urls import path
from . import views
from .views import (
    ServiceListView,
    ServiceCreateView, ServiceUpdateView, ServiceDeleteView, ServiceStatusAPIView
)

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('services/', ServiceListView.as_view(), name='services'),
    path('services/add/', ServiceCreateView.as_view(), name='service_add'),
    path('services/<int:pk>/edit/', ServiceUpdateView.as_view(), name='service_edit'),
    path('services/<int:pk>/delete/', ServiceDeleteView.as_view(), name='service_delete'),
    path('services/status/', ServiceStatusAPIView.as_view(), name='service_status'),
    path('system/', views.SystemView.as_view(), name='system'),
]