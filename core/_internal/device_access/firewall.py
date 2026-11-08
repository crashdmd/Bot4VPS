"""Local LXC firewall only; no SSH or changes to managed VPS settings.

The journal precedes mutations so interrupted operations can be retried.
Only dedicated UFW profiles, newly added firewalld ports and tagged rules
in Bot4VPS's own nftables table are removed. No global reload/enable/flush.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import uuid

from core.json_store import atomic_write_json, locked

STATE_PATH = Path("data/mobile-api-firewall.json")
UFW_PROFILES = Path("/etc/ufw/applications.d")
NFT_CONF = Path("/etc/nftables.d/bot4vps.conf")
NFT_MAIN = Path("/etc/nftables.conf")
NFT_HEADER = "# Managed by Bot4VPS: базовый nftables ruleset (таблица bot4vps)."
_LOCK = threading.RLock()


class FirewallError(RuntimeError):
    pass


def _run(*args, allowed=(0,)):
    try:
        result = subprocess.run(list(args), capture_output=True, text=True, timeout=20,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FirewallError(f"Локальный файрволл: не удалось выполнить {args[0]}") from exc
    if result.returncode not in allowed:
        raise FirewallError(f"Локальный файрволл: {args[0]}: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout.strip(), result.returncode


def _atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            name = out.name
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


class LocalApiFirewall:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else STATE_PATH

    def _read(self):
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
            if raw.get("version") != 1 or not isinstance(raw.get("rules"), list):
                raise ValueError()
            rules = raw["rules"]
            for rule in rules:
                if (rule.get("backend") not in ("ufw", "firewalld", "nft")
                        or not re.fullmatch(r"[0-9a-f]{32}", rule.get("id", ""))
                        or type(rule.get("port")) is not int or not 1 <= rule["port"] <= 65535):
                    raise ValueError()
                if rule["backend"] == "firewalld":
                    if not isinstance(rule.get("parts"), list):
                        raise ValueError()
                    for part in rule["parts"]:
                        if (not re.fullmatch(r"[A-Za-z0-9_-]+", part.get("zone", ""))
                                or type(part.get("permanent")) is not bool):
                            raise ValueError()
            return rules
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise FirewallError("Не удалось прочитать учёт правил API; автоматическая очистка остановлена") from exc

    def _write(self, rules):
        atomic_write_json(self.path, {"version": 1, "rules": rules})

    def _nft_ruleset(self):
        try:
            return json.loads(_run("nft", "-j", "list", "ruleset")[0])["nftables"]
        except (ValueError, KeyError, TypeError) as exc:
            raise FirewallError("Не удалось прочитать локальные правила nftables") from exc

    def _detect(self):
        if shutil.which("ufw"):
            status = _run("ufw", "status")[0]
            if status.startswith("Status: active"):
                return "ufw"
            if not status.startswith("Status: inactive"):
                raise FirewallError("Не удалось определить состояние локального UFW")
        if shutil.which("firewall-cmd"):
            status, code = _run("firewall-cmd", "--state", allowed=(0, 252))
            if code == 0 and status == "running":
                return "firewalld"
            if code != 252:
                raise FirewallError("Не удалось определить состояние локального firewalld")
        if shutil.which("nft"):
            entries = self._nft_ruleset()
            chains = [e["chain"] for e in entries if "chain" in e and e["chain"].get("hook") == "input"]
            if chains:
                if (len(chains) == 1 and chains[0].get("family") == "inet"
                        and chains[0].get("table") == "bot4vps" and chains[0].get("name") == "input"):
                    self._check_nft_persistence()
                    return "nft"
                raise FirewallError("Локальный nftables использует сторонние входящие цепочки; правило API не применено")
        # Legacy iptables may not appear in nft's ruleset.
        for command in ("iptables-save", "ip6tables-save"):
            if shutil.which(command):
                output = _run(command)[0]
                if re.search(r"^:INPUT (DROP|REJECT)|^-A INPUT\b", output, re.M):
                    raise FirewallError("Локальный iptables настроен вручную; правило API не применено")
        return "none"

    def _check_nft_persistence(self):
        if (not NFT_CONF.is_file() or not NFT_CONF.read_text().startswith(NFT_HEADER + "\n")
                or not NFT_MAIN.is_file() or not re.search(r'^\s*include "/etc/nftables\.d/bot4vps\.conf"\s*(?:#.*)?$', NFT_MAIN.read_text(), re.M)):
            raise FirewallError("Не найден управляемый Bot4VPS конфиг локального nftables")

    def _persist_nft(self):
        self._check_nft_persistence()
        content = _run("nft", "list", "table", "inet", "bot4vps")[0]
        _atomic_text(NFT_CONF, f"{NFT_HEADER}\n{content}\n")

    @staticmethod
    def _profile(rule):
        return f"Bot4VPS-Mobile-{rule['port']}-{rule['id']}"

    def _profile_content(self, rule):
        name = self._profile(rule)
        return f"[{name}]\ntitle=Bot4VPS Mobile API\ndescription=Managed by Bot4VPS Mobile {rule['id']}\nports={rule['port']}/tcp\n"

    def _ufw(self, rule, opening):
        name = self._profile(rule)
        path = UFW_PROFILES / name
        content = self._profile_content(rule)
        if path.exists() and path.read_text() != content:
            raise FirewallError("Профиль UFW для API изменён вручную; очистка остановлена")
        added = _run("ufw", "show", "added")[0]
        # Match the exact profile token, including UFW's optional quoting.
        present = any(line.startswith("ufw allow ") and any(token.strip("'\"") == name for token in line.split())
                      for line in added.splitlines())
        if opening:
            if not path.exists():
                _atomic_text(path, content)
            if not present:
                _run("ufw", "insert", "1", "allow", name, "comment", "Bot4VPS Mobile API")
            added = _run("ufw", "show", "added")[0]
            if name not in added:
                raise FirewallError("UFW не подтвердил добавление правила API")
        else:
            if present:
                # Recreate our exact profile if it was lost, for precise deletion.
                if not path.exists():
                    _atomic_text(path, content)
                _run("ufw", "--force", "delete", "allow", name)
                if name in _run("ufw", "show", "added")[0]:
                    raise FirewallError("UFW не подтвердил удаление правила API")
            path.unlink(missing_ok=True)

    @staticmethod
    def _fw_args(part):
        return ["firewall-cmd", *(["--permanent"] if part["permanent"] else []), "--zone=" + part["zone"]]

    def _firewalld(self, rule, opening, rules):
        if opening:
            active = _run("firewall-cmd", "--get-active-zones")[0]
            zones = [line.strip() for line in active.splitlines() if line and not line[0].isspace()]
            if not zones:
                zones = [_run("firewall-cmd", "--get-default-zone")[0]]
            for zone in zones:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", zone):
                    raise FirewallError("Некорректная локальная зона firewalld")
                for permanent in (False, True):
                    part = {"zone": zone, "permanent": permanent}
                    args = self._fw_args(part)
                    _, code = _run(*args, f"--query-port={rule['port']}/tcp", allowed=(0, 1))
                    if code == 1:
                        if part not in rule["parts"]:
                            rule["parts"].append(part)
                            self._write(rules)  # Intent before mutation, including each zone/scope.
                        _run(*args, f"--add-port={rule['port']}/tcp")
                        _, code = _run(*args, f"--query-port={rule['port']}/tcp", allowed=(0, 1))
                        if code != 0:
                            raise FirewallError("firewalld не подтвердил открытие порта API")
        else:
            for part in rule["parts"][:]:
                # Permanent settings remain editable while firewalld is stopped.
                if part["permanent"]:
                    _, status = _run("firewall-cmd", "--state", allowed=(0, 252))
                    args = self._fw_args(part) if status == 0 else ["firewall-offline-cmd", "--zone=" + part["zone"]]
                else:
                    _, status = _run("firewall-cmd", "--state", allowed=(0, 252))
                    if status == 252:
                        rule["parts"].remove(part)
                        self._write(rules)
                        continue
                    args = self._fw_args(part)
                _, code = _run(*args, f"--query-port={rule['port']}/tcp", allowed=(0, 1))
                if code == 0:
                    _run(*args, f"--remove-port={rule['port']}/tcp")
                    _, code = _run(*args, f"--query-port={rule['port']}/tcp", allowed=(0, 1))
                    if code != 1:
                        raise FirewallError("firewalld не подтвердил закрытие порта API")
                rule["parts"].remove(part)
                self._write(rules)

    def _nft(self, rule, opening):
        tag = "bot4vps-mobile-" + rule["id"]
        entries = self._nft_ruleset()
        matches = [e["rule"] for e in entries if "rule" in e and e["rule"].get("comment") == tag]
        for match in matches:
            if (match.get("family"), match.get("table"), match.get("chain")) != ("inet", "bot4vps", "input"):
                raise FirewallError("Правило API nftables перемещено вручную; очистка остановлена")
        if opening:
            self._check_nft_persistence()
            if not matches:
                _run("nft", "insert", "rule", "inet", "bot4vps", "input", "tcp", "dport", str(rule["port"]),
                     "counter", "accept", "comment", '"' + tag + '"')
                if not any(e.get("rule", {}).get("comment") == tag for e in self._nft_ruleset()):
                    raise FirewallError("nftables не подтвердил добавление правила API")
            self._persist_nft()
        else:
            for match in matches:
                _run("nft", "delete", "rule", "inet", "bot4vps", "input", "handle", str(int(match["handle"])))
            # Even if the runtime rule is absent, remove it from the boot config.
            if matches or NFT_CONF.exists() and tag in NFT_CONF.read_text():
                self._persist_nft()

    def _apply(self, rule, opening, rules):
        if rule["backend"] == "ufw":
            self._ufw(rule, opening)
        elif rule["backend"] == "firewalld":
            self._firewalld(rule, opening, rules)
        else:
            self._nft(rule, opening)

    def sync(self, port: int | None):
        """Converge to the enabled port (None = disabled); retry owned cleanup.

        On failure the remaining journal is retained. The caller must stop a
        candidate listener and may call sync(old_port) to roll back a change.
        """
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("Некорректный порт API")
        if port is None and not self.path.exists():
            return "API выключен; правил для удаления нет."
        with locked(self.path.with_name(self.path.name + ".lock"), _LOCK):
            rules = self._read()
            backend = self._detect() if port is not None else "none"
            target = next((r for r in rules if r["port"] == port and r["backend"] == backend), None)
            if port is not None and backend != "none":
                if target is None:
                    target = {"id": uuid.uuid4().hex, "port": port, "backend": backend, "parts": []}
                    rules.append(target)
                    self._write(rules)
                self._apply(target, True, rules)
            for rule in rules[:]:
                if rule is not target:
                    self._apply(rule, False, rules)
                    rules.remove(rule)
                    self._write(rules)
            if port is None:
                return "Правило API удалено из локального файрволла LXC."
            if backend == "none":
                return "Локальный файрволл не ограничивает входящие соединения; дополнительное правило не требуется."
            return f"TCP-порт {port} открыт в локальном файрволле LXC ({backend})."
