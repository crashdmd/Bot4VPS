"""Подсистема сервисов Bot4VPS (дорожка «Сервисы», параллельная «Скриптам»).

Каждый сервис — отдельная подпапка с собственным service.json и модулем:
    services/<id>/__init__.py
    services/<id>/service.json     # данные (идентификатор, пакеты, флаги)
    services/<id>/<id>.py          # class Service(core.integrator.Service) — вся логика

Движок — в core/integrator.py. Зависимость однонаправленная: сюда → core.
"""
