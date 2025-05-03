from django import forms
from .models import Service
from django.utils.translation import gettext_lazy as _

class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ['name', 'hostname', 'address', 'port', 'status']
        labels = {
            'name': _('Название'),
            'hostname': _('Hostname'),
            'address': _('Адрес'),
            'port': _('Порт'),
            'status': _('Статус мониторинга'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'port': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }