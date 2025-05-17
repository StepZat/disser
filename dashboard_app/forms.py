from django import forms
from .models import Service, Host
from django.utils.translation import gettext_lazy as _

class ServiceForm(forms.ModelForm):

    class Meta:
        model  = Service
        fields = ['name', 'hostname', 'address', 'port', 'protocol']
        labels = {
            'name': _('Название'),
            'hostname': _('Hostname'),
            'address': _('Адрес'),
            'port': _('Порт'),
            'protocol': _('Протокол'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control'}),
            'hostname': forms.TextInput(attrs={'class':'form-control'}),
            'address': forms.TextInput(attrs={'class':'form-control'}),
            'port': forms.NumberInput(attrs={'class':'form-control'}),
            'protocol': forms.Select(attrs={'class':'form-control'}),
        }

class HostForm(forms.ModelForm):
    class Meta:
        model = Host
        fields = ['name', 'address']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Имя хоста'),
                # id будет «id_name» автоматически
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('IP или hostname'),
            }),
        }
        labels = {
            'name': _('Имя'),
            'address': _('Адрес'),
        }
