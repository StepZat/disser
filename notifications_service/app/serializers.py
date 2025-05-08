# app/serializers.py
from rest_framework import serializers
from .models import Property

class EmailNotifySerializer(serializers.Serializer):
    to_email = serializers.EmailField()
    subject  = serializers.CharField(max_length=255)
    body     = serializers.CharField()

class TelegramNotifySerializer(serializers.Serializer):
    chat_id = serializers.CharField()
    message = serializers.CharField()

class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Property
        fields = ["key", "value"]