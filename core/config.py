import json
import os

from pathlib import Path

CONFIG_FILE = Path("config.json")
TEMP_FILE = Path("config.json.tmp")


DEFAULT_CONFIG = {
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "allowed_users": [],
    "monitor": {
        "online": {
            "enabled": True,
            "interval": 5
        },
        "ssl": {
            "enabled": True,
            "interval": 1440
        }
    }
}


def load_config():

    if not CONFIG_FILE.exists():

        save_config(DEFAULT_CONFIG)

        return DEFAULT_CONFIG.copy()

    with open(
        CONFIG_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        config = json.load(f)

    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            changed = True
    monitor = config.setdefault("monitor", {})
    for name, settings in DEFAULT_CONFIG["monitor"].items():
        if name not in monitor:
            monitor[name] = settings
            changed = True
    if changed:
        save_config(config)
    return config


def save_config(config):

    with open(
        TEMP_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            config,
            f,
            indent=4,
            ensure_ascii=False
        )

        f.flush()
        os.fsync(f.fileno())

    os.replace(
        TEMP_FILE,
        CONFIG_FILE
    )


def get_monitor_config():

    return load_config()["monitor"]


def set_monitor_enabled(name, enabled):

    config = load_config()

    config["monitor"][name]["enabled"] = enabled

    save_config(config)


def set_monitor_interval(name, interval):

    config = load_config()

    config["monitor"][name]["interval"] = interval

    save_config(config)