# auth_app/forms.py
from django.contrib.auth.forms import AuthenticationForm
from django import forms
from django.utils.translation import gettext_lazy as _


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label=_('Имя пользователя'),
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('Имя пользователя'),
            }
        )
    )
    password = forms.CharField(
        label=_('Пароль'),
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('Пароль'),
            }
        )
    )