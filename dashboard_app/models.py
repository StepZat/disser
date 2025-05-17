from django.db import models

class Service(models.Model):
    name      = models.CharField(max_length=100, verbose_name="Название")
    hostname  = models.CharField(max_length=100, verbose_name="Hostname")
    address   = models.GenericIPAddressField(verbose_name="Адрес")
    port      = models.PositiveIntegerField(verbose_name="Порт")
    PROTO_CHOICES = [
    ('tcp', 'TCP'),
    ('http', 'HTTP'),]
    protocol = models.CharField(
        max_length = 5,
        choices = PROTO_CHOICES,
        default = 'tcp',
        help_text = "Метод проверки: TCP-коннект или HTTP-запрос"
       )

    last_is_up = models.BooleanField(
        null=True,
        blank=True,
        help_text="Последний известный статус: True=Up, False=Down, NULL=неизвестно"
    )

    objects = models.Manager()

    class Meta:
        verbose_name = "Сервис"
        verbose_name_plural = "Сервисы"
        ordering = ['name']

    def __str__(self):
        return self.name

class Host(models.Model):
    name    = models.CharField("Имя", max_length=100, unique=True)
    address = models.CharField("Адрес (IP или hostname)", max_length=100)
    is_up        = models.BooleanField(
        null=True, blank=True,
        verbose_name="Доступен (ping)"
    )

    def __str__(self):
        return self.name