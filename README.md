# 🚀 Bot4VPS

Telegram-бот для удобного управления VPS и домашними серверами через SSH.
**Примечание:** Бот делался универсальным, под свои нужды, без претензий на исключительность — с помощью ИИ.

## Возможности

### 🖥 Управление серверами

- Группировка серверов (`home`, `vps` и пользовательские группы)
- Пошаговый мастер добавления серверов
- SSH-аутентификация:
  - по паролю
  - по приватному ключу
- Автоматическая проверка SSH при добавлении и редактировании
- Возможность сохранить изменения даже при ошибке проверки SSH
- Просмотр состояния сервера:
  - Uptime
  - Load Average
  - Использование RAM
  - Использование диска
- Перезагрузка сервера
- Редактирование и удаление серверов

---

### 🔐 Мониторинг SSL

- Автоматическая ежедневная проверка сертификатов
- Уведомления в Telegram:
  - обновление сертификата
  - скорое истечение срока действия
- Ручная проверка сертификатов через меню группы
- Гибридная проверка доступности (Ping + HTTP)

---

### 📜 Выполнение скриптов

- Запуск Shell-скриптов через Telegram
- Поддержка пользовательских параметров (`# BOT_PARAM`)
- Поддержка условных параметров
- Просмотр списка скриптов
- Удаление скриптов через интерфейс бота

---

## Требования

- Python 3.11+
- Telegram Bot Token
- SSH-доступ к серверам

---

# Установка

Клонирование репозитория:

```bash
git clone https://github.com/crashdmd/Bot4VPS.git
cd Bot4VPS
```

Создание виртуального окружения:

```bash
python3 -m venv venv
source venv/bin/activate
```

Установка зависимостей:

```bash
pip install -r requirements.txt
```

---

# Конфигурация

Создайте файл конфигурации:

```bash
cp config.example.json config.json
```

Отредактируйте `config.json`:

```json
{
    "bot_token": "YOUR_BOT_TOKEN",
    "allowed_users": [
        123456789
    ]
}
```

Создайте необходимые директории:

```bash
mkdir -p scripts keys backup
```

---

# Запуск

```bash
python3 bot.py
```

---

# Автозапуск через systemd

Создайте сервис:

`/etc/systemd/system/bot4vps.service`

```ini
[Unit]
Description=Bot4VPS Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bot4vps
ExecStart=/opt/bot4vps/venv/bin/python /opt/bot4vps/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Примените изменения:

```bash
systemctl daemon-reload
systemctl enable --now bot4vps
```

Проверить статус:

```bash
systemctl status bot4vps
```

Просмотреть журнал:

```bash
journalctl -u bot4vps -f
```

---

# Структура проекта

```text
Bot4VPS/
├── bot.py                 # Главный файл
├── servers.py             # Управление серверами
├── server_wizard.py       # Мастер добавления/редактирования
├── scripts.py             # Выполнение скриптов
├── script_utils.py        # Работа со скриптами
├── ssh_utils.py           # SSH-подключения
├── storage.py             # Работа с данными
├── monitor.py             # Мониторинг SSL
├── ui.py                  # Telegram-клавиатуры
├── state.py               # FSM-состояния
├── requirements.txt
├── config.example.json
└── README.md
```

---

# Безопасность

- Доступ к боту имеют только пользователи из `allowed_users`.
- При каждом изменении серверов автоматически создаётся резервная копия `servers.json` в каталоге `backup/`.
- Пароли и SSH-ключи не отображаются в интерфейсе бота.

---

# Планы

- [ ] Управление SSH-ключами через интерфейс бота
- [ ] Массовое выполнение скриптов
- [ ] Web-интерфейс
- [ ] Docker-образ

---
