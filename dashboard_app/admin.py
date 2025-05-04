from django.contrib import admin
from .models import Service

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'hostname', 'address', 'port')
    list_filter = ()
    search_fields = ('name', 'hostname')
