from django import forms
from .models import Service, Host
from django.utils.translation import gettext_lazy as _

class ServiceForm(forms.ModelForm):
    role = forms.ChoiceField(
        choices=Service.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
        label=_('Роль'),
    )

    class Meta:
        model  = Service
        fields = ['name', 'hostname', 'address', 'port', 'protocol', 'enable_monitoring', 'role']
        labels = {
            'name': _('Название'),
            'hostname': _('Hostname'),
            'address': _('Адрес'),
            'port': _('Порт'),
            'protocol': _('Протокол'),
            'enable_monitoring': _('Установить мониторинг'),
            'role': _('Роль'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control'}),
            'hostname': forms.TextInput(attrs={'class':'form-control'}),
            'address': forms.TextInput(attrs={'class':'form-control'}),
            'port': forms.NumberInput(attrs={'class':'form-control'}),
            'protocol': forms.Select(attrs={'class':'form-control'}),
            'enable_monitoring': forms.CheckboxInput(attrs={'class':'form-check-input'}),
            'role': forms.Select(attrs={'class':'form-select'}),
        }

class HostForm(forms.ModelForm):
    class Meta:
        model = Host
        fields = ["name", "address"]