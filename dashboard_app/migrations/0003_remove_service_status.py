# Generated by Django 5.2 on 2025-05-04 09:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard_app', '0002_alter_service_status'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='service',
            name='status',
        ),
    ]
