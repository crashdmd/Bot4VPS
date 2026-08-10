# Unified process: Web + Telegram

## Запуск

```bash
cd /opt/bot4vps
source venv/bin/activate
PYTHONPATH=. uvicorn ui.web.app:app --host 0.0.0.0 --port 8080
```

Один процесс:
- FastAPI / Web UI
- Telegram bot (PTB manual lifecycle)
- TaskManager (общий)
- monitor jobs (PTB job_queue)

## Systemd

1. Скопировать `deploy/bot4vps.service` → `/etc/systemd/system/bot4vps.service`
2. Отключить старые раздельные юниты:
   ```bash
   systemctl disable --now bot4vps-web.service
   # если был отдельный бот:
   systemctl disable --now bot4vps-bot.service  # или как назывался
   ```
3. ```bash
   systemctl daemon-reload
   systemctl enable --now bot4vps.service
   ```

## Standalone Telegram only

```bash
PYTHONPATH=. python bot.py
```

## Замечания

- `register_notifier(..., replace=True)` — без дублей уведомлений при reload
- Смена monitor в Web сразу вызывает `schedule_monitor_jobs`
- Не использовать `uvicorn --reload` в проде (в dev — ок, notifier сбрасывается)
