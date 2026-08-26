from __future__ import annotations

import posixpath
import stat

# Ровно псевдо-ФС, названные в ТЗ. Никакого расширенного denylist и авто-
# определения по типу mount: критерий Full обязан быть простым и
# детерминированным, а не «обычно это не бэкапят».
RUNTIME_PSEUDO_FS = ("/proc", "/sys", "/dev", "/run")


def enumerate_full_root_sources(ssh) -> list[str]:
    """Реальные top-level каталоги ``/`` минус :data:`RUNTIME_PSEUDO_FS`.

    Это «полный набор» R: набор источников, при совпадении с которым backup
    считается полным. Классификация ОБЯЗАНА совпадать с SFTP-браузером профиля
    (:func:`ui.web.backup_runtime._browse_sftp_impl`): каталог — это
    ``S_ISDIR(st_mode) and not S_ISLNK(st_mode)``. Иначе «кнопка Full» и ручной
    выбор тех же корней во вкладке «Профиль» дали бы разные наборы и разный
    критерий полноты.

    Верхнеуровневые симлинки (``/bin -> /usr/bin`` и т.п.) исключаются: браузер
    помечает их ``is_symlink`` и пользователь не выбирает их как папку, а заодно
    не дублируется содержимое цели. ``listdir_attr('/')`` не требует sudo — ``/``
    имеет режим 0755.
    """
    with ssh.open_sftp() as sftp:
        roots: list[str] = []
        for entry in sftp.listdir_attr("/"):
            mode = entry.st_mode or 0
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                path = posixpath.join("/", entry.filename)  # '/etc', '/var', ...
                if path not in RUNTIME_PSEUDO_FS:
                    roots.append(path)
        return sorted(roots)
