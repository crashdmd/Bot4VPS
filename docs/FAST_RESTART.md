# Инструкция: Быстрый перезапуск bot4vps с активными браузерными соединениями

## Проблема
При `systemctl restart bot4vps` systemd ждёт graceful shutdown — uvicorn держит активные WebSocket/SSE соединения открытыми, пока браузер не отключится. Перезапуск может занимать до 90 секунд (дефолтный TimeoutStopSec).

## Решение
Добавлены параметры в `deploy/bot4vps.service`:
- **TimeoutStopSec=3** — systemd ждёт 3 секунды, затем принудительно завершает процесс
- **KillMode=mixed** — SIGTERM главному процессу + SIGKILL дочерним процессам

## Применение изменений

```bash
# 1. Обновить service-файл на сервере
cd /opt/bot4vps
git pull  # или скопировать новый deploy/bot4vps.service вручную

# 2. Скопировать обновлённый unit в systemd
sudo cp deploy/bot4vps.service /etc/systemd/system/bot4vps.service

# 3. Перезагрузить конфигурацию systemd
sudo systemctl daemon-reload

# 4. Перезапустить сервис (теперь быстро, ~3 секунды)
sudo systemctl restart bot4vps

# 5. Проверить статус
sudo systemctl status bot4vps
```

## Проверка

До изменений:
```bash
time sudo systemctl restart bot4vps  # ~30-90 секунд с открытым браузером
```

После изменений:
```bash
time sudo systemctl restart bot4vps  # ~3 секунды независимо от браузера
```

## Безопасность

- **Graceful shutdown** по-прежнему работает для задач (SSH-операции, docker pull и т.д.)
- Активные задачи очереди (`task_manager.py`) завершаются корректно
- Теряются только незавершённые HTTP-запросы и живые SSE/WebSocket (браузер автоматически переподключится)
- Данные в БД и кэше сохраняются

## Альтернатива (если нужен ещё более быстрый restart)

Можно снизить до 1 секунды:
```ini
TimeoutStopSec=1
```

Или вообще без ожидания (мгновенное убийство):
```ini
TimeoutStopSec=0
KillMode=process
```
(не рекомендуется — может прервать SSH-операции)

## Откат изменений

Если нужно вернуть старое поведение:
```bash
# Удалить строки TimeoutStopSec и KillMode из /etc/systemd/system/bot4vps.service
sudo systemctl daemon-reload
sudo systemctl restart bot4vps
```
