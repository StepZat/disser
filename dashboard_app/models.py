from django.db import models

class Service(models.Model):
    name      = models.CharField(max_length=100, verbose_name="Название")
    hostname  = models.CharField(max_length=100, verbose_name="Hostname")
    address   = models.GenericIPAddressField(verbose_name="Адрес")
    port      = models.PositiveIntegerField(verbose_name="Порт")
    # новый функционал
    enable_monitoring = models.BooleanField(
        default=False,
        verbose_name="Установить мониторинг"
    )
    ROLE_CHOICES = [
        ('mongodb',    'MongoDB'),
        ('mysql',      'MySQL'),
        ('postgresql', 'PostgreSQL'),
        ('common',     'Common'),
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='common',
        verbose_name='Роль',
        blank=True,
    )

    objects = models.Manager()

    class Meta:
        verbose_name = "Сервис"
        verbose_name_plural = "Сервисы"
        ordering = ['name']

    def __str__(self):
        return self.name
