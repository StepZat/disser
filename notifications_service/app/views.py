# app/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets

from .config import NotificationConfig
from .models import Property
from .serializers import EmailNotifySerializer, TelegramNotifySerializer, PropertySerializer
from .notifications import send_email, send_telegram

class EmailNotifyView(APIView):
    def post(self, request):
        ser = EmailNotifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        send_email(**ser.validated_data)
        return Response({"detail": "Email sent"}, status=status.HTTP_200_OK)

class TelegramNotifyView(APIView):
    def post(self, request):
        ser = TelegramNotifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        send_telegram(ser.validated_data["chat_id"], ser.validated_data["message"])
        return Response({"detail": "Telegram message sent"}, status=status.HTTP_200_OK)

class PropertyViewSet(viewsets.ModelViewSet):
    queryset         = Property.objects.all()
    serializer_class = PropertySerializer
    lookup_field     = "key"

    def perform_create(self, serializer):
        obj = serializer.save()
        NotificationConfig.load()              # обновить кэш

    def perform_update(self, serializer):
        obj = serializer.save()
        NotificationConfig.load()              # обновить кэш