# Generated by Django 5.2 on 2025-05-17 19:00

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard_app', '0008_host_is_up'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='service',
            name='enable_monitoring',
        ),
        migrations.RemoveField(
            model_name='service',
            name='role',
        ),
    ]
