from django.db import models

class Service(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название")
    hostname = models.CharField(max_length=100, verbose_name="Имя хоста")
    address = models.GenericIPAddressField(verbose_name="IP-Адрес")
    port = models.PositiveIntegerField(verbose_name="Порт")
    status = models.CharField(
        max_length=20,
        choices=[('OK', 'OK'), ('DOWN', 'DOWN')],
        default='OK',
        verbose_name="Статус мониторинга"
    )

    class Meta:
        verbose_name = "Сервис"
        verbose_name_plural = "Сервисы"
        ordering = ['name']

    def __str__(self):
        return self.name