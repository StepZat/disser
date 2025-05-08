# app/urls.py
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EmailNotifyView, TelegramNotifyView, PropertyViewSet

router = DefaultRouter()
router.register(r"properties", PropertyViewSet, basename="properties")

urlpatterns = [
    *router.urls,
    path("notify/email/",    EmailNotifyView.as_view(),    name="notify-email"),
    path("notify/telegram/", TelegramNotifyView.as_view(), name="notify-telegram"),
]
