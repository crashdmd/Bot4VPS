# Bot4VPS Web UI

Веб-слой (FastAPI + SPA на ванильном JS) поверх **core** — без Telegram. Даёт тот
же функционал: серверы и SSH-сессии, очереди задач, скрипты с параметрами,
мониторинг доступности и SSL, журнал событий, файлы и SSH-ключи.

## Запуск

Из **корня** репозитория Bot4VPS (рядом с `core/`, `servers.json`, `config.json`):

```bash
pip install fastapi uvicorn
PYTHONPATH=. uvicorn ui.web.app:app --reload --host 127.0.0.1 --port 8080
```

Открыть: http://127.0.0.1:8080/

> ⚠️ Биндите на `127.0.0.1`, если не включена авторизация (см. ниже). На `0.0.0.0`
> сервис виден всей сети, а часть эндпоинтов выполняет произвольные команды и
> отдаёт приватные SSH-ключи.

## Авторизация

По умолчанию **выключена** (`web.auth_enabled = false`) — рассчитано на локальный
запуск. Чтобы включить:

```jsonc
// config.json
"web": {
  "auth_enabled": true,
  "username": "admin",
  "password_hash": "",     // pbkdf2_sha256$<iters>$<salt>$<hex>
  "secret_key": ""         // подпись сессионной куки, генерируется автоматически
}
```

- **Где хранится:** учётка — в `config.json` (секция `web`), рядом с `bot_token`.
  Пароль хешируется **PBKDF2-HMAC-SHA256** (stdlib, без новых зависимостей).
  `secret_key` для подписи куки генерируется при первом старте (`ensure_web_secrets()`).
- **Первый запуск с включённой авторизацией и пустым `password_hash`**: в консоль
  печатается одноразовый пароль. Сменить его:
  `POST /api/auth/password` (`{old, new}`, new ≥ 6 символов) — из UI или curl.
- Сессия — подписанная кука `bot4vps_sid` (7 дней), ставится через `POST /api/login`.
- Все `/api/*`-роутеры закрыты зависимостью `require_auth`; без авторизации
  `GET /api/me` вернёт 401, и UI покажет оверлей входа.

## Важные ограничения

- **`task_manager` — in-memory** (`core/task_manager.py`), а веб-процесс отдельный
  от `bot.py`. Очереди и история задач видны только в том процессе, где они
  запущены: задачи из Telegram не видны в вебе, и наоборот. Для единого состояния
  нужен внешний сторадж — сейчас его нет.
- Живой probe/metrics/exec/shell ходят по SSH через тот же `core.ssh.create_ssh_client`
  (paramiko). Долгие операции — в `asyncio.to_thread`, event loop не блокируется.
- Постоянные SSH-сессии терминала (`/api/servers/{id}/exec` с `session:true`) —
  in-memory, по одной на сервер, без тайм-аута простоя (закрываются через
  `/shell/close` или перезапуск).

## API

### Авторизация (без auth-гейта)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/me` | статус сессии / флаг `auth_enabled` |
| POST | `/api/login` | `{username, password}` → сессия |
| POST | `/api/logout` | сброс сессии |
| POST | `/api/auth/password` | смена пароля `{old, new}` |

### Метa
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/ping` | время, версия, cwd |
| GET | `/api/routes` | список зарегистрированных роутов |
| GET | `/api/summary` | сводка: серверы, активные очереди, executors |
| GET | `/api/stream` | SSE-снапшот дашборда каждые ~3с |

### Серверы
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/servers` | список (`?group=`, `?online=`) + monitor + очереди |
| POST | `/api/servers` | создать (`test:true` — пробовать SSH перед сохранением) |
| GET | `/api/servers/{id}` | карточка: storage + monitor + очередь |
| PATCH | `/api/servers/{id}` | обновить поля |
| DELETE | `/api/servers/{id}` | удалить |
| GET | `/api/servers/{id}/metrics` | CPU/RAM/Диск/Load/Uptime (одной SSH-командой) |
| GET | `/api/servers/{id}/probe` | ping + SSH-метрики (`get_server_info`) |
| GET | `/api/servers/{id}/ping` | TCP-латентность до host:port |
| POST | `/api/servers/{id}/exec` | выполнить команду (`{command, session}`) |
| POST | `/api/servers/{id}/reboot` | перезагрузка |
| POST | `/api/servers/{id}/shell/close` | закрыть постоянную SSH-сессию |
| POST | `/api/servers/{id}/test` · `/test-connection` · `/test-draft` · `/api/ssh/test` | проверка SSH по полям формы |

### Задачи и очереди
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/tasks/enqueue` | `{script_name, server_id, values?}` → `enqueue_script` |
| GET | `/api/queues` | активные очереди по серверам |
| GET | `/api/tasks/history` | история (`?limit=`, `?server_id=`) |
| GET | `/api/tasks/{id}` | полная карточка задачи |
| POST | `/api/queues/{id}/continue` · `/retry` · `/clear` | управление очередью |

### Скрипты
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/scripts` | список + `params` (с `options`/`condition`) |
| GET | `/api/scripts/{name}` | исходник + метаданные |
| POST | `/api/upload/script` | залить `.sh` |

DSL параметров (`core/script_utils.get_script_params`):

```
# BOT_PARAM <name> <type> [if=<param>:<value>] <label>
# BOT_OPTION <name> <value> <label>
```

Типы: `text`, `number`, `bool`, `select`. Условие `if=NAME:value` показывает поле
только если параметр `NAME` равен `value` (case-insensitive). Значения injectingся
как env-переменные при запуске.

### Файлы и ключи
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/files?root=scripts\|keys` | список |
| GET | `/api/files/download` | скачать |
| POST | `/api/files/upload` | залить |
| DELETE | `/api/files` | удалить (+ `.pub` пара для keys) |
| POST | `/api/keys/create` | создать ed25519 |
| GET | `/api/keys/view` | содержимое приватного ключа |
| GET | `/api/groups` · `/api/keys` | группы / список ключей |

### Мониторинг и события
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/monitor/config` | интервалы online/ssl |
| POST | `/api/monitor/config` | `{name, enabled?, interval?}` |
| POST | `/api/monitor/check/online\|ssl` | прогнать проверку сейчас (с события) |
| GET | `/api/events` | журнал (`?limit=`) |
| DELETE | `/api/events` | очистить журнал |

## Структура

```
ui/web/
  app.py              FastAPI, middleware, lifespan, auth-эндпоинты
  security.py         PBKDF2 + require_auth
  deps.py             err(), task_brief(), queue_state_dict(), VERSION
  routers/            meta, summary, servers, tasks, scripts, files, monitor, stream
  static/             index.html + css/ + js/ (SPA: api, app, auth, dashboard,
                     servers, scripts, files, monitor, sse, state, terminal, ui)
```
