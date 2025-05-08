# app/models.py
from django.db import models

class Property(models.Model):
    key   = models.CharField(max_length=100, unique=True)
    value = models.TextField()

    def __str__(self):
        return f"{self.key}"