# app/config.py

from .models import Property

class ConfigError(Exception):
    pass

class NotificationConfig:
    """Хранит все параметры в памяти, загруженные при старте."""
    _props: dict[str, str] = {}

    @classmethod
    def load(cls):
        # Считываем все записи из БД единожды
        cls._props = {p.key: p.value for p in Property.objects.all()}

    @classmethod
    def get(cls, key: str) -> str:
        try:
            return cls._props[key]
        except KeyError:
            raise ConfigError(f"Property '{key}' not found in loaded config")
