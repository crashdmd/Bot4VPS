"""Консольное меню управления Bot4VPS (ui/cli).

Тонкий интерфейс поверх Core — третий вход наряду с Web UI и Telegram:

                ┌── Web UI
                │
Bot4VPS Core ───┼── Telegram
                │
                └── CLI (этот пакет)

CLI не дублирует бизнес-логику: настройки меняются через core.config,
Web-порт — через core.web_port, пароль — через ui.web.security, обновление —
через core.update. Единственная собственная территория — управление
systemd-сервисом и firewall (systemd_ops.py), перенесённое из install.sh.

install.sh — reference для install/remove-поведения, но НЕ runtime-зависимость:
после `rm install.sh` команда bot4vps продолжает полноценно работать.
"""
