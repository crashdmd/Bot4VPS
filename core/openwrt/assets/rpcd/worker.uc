#!/usr/bin/ucode
'use strict';
import { readfile, writefile, open, access, mkdir, stat, unlink, rename, glob, popen } from 'fs';
import { connect } from 'ubus';
import * as agh from '/usr/share/bot4vps/adguard.uc';

let username = ARGV[0], nonce = ARGV[1];
if (!match(username || '', /^bot4vps_[a-f0-9]+$/) || !match(nonce || '', /^[a-f0-9]{32}$/)) exit(1);
let dir = '/tmp/bot4vps-jobs/' + username + '/' + nonce;
let message = json(readfile(dir + '/manifest.json') || '{}');
let plan = json(readfile(dir + '/plan.json') || '{}');
function put_file(path, data, mode) {
    let file = open(path, 'w', mode == null ? 0600 : mode);
    if (!file) die('Не удалось сохранить файл операции');
    file.write(data);
    file.close();
}

function quote(s) { return "'" + replace(s, "'", "'\\''") + "'"; }
function log(text) {
    let f = open(dir + '/log', 'a', 0600);
    if (f) { f.write(text + '\n'); f.close(); }
}
function state(phase, error) {
    put_file(dir + '/state.new', sprintf('%J', { phase, error: error || null, updated_at: time() }), 0600);
    rename(dir + '/state.new', dir + '/state.json');
}
function command(cmd) {
    let pipe = popen(cmd + ' 2>&1');
    if (!pipe) die('Не удалось запустить шаг');
    let line;
    while ((line = pipe.read('line')) != null) log(trim(line));
    let result = pipe.close();
    if (result != 0) die('Шаг завершился с ошибкой (' + result + ')');
}
function hash(path) {
    let p = popen('sha256sum ' + quote(path) + ' 2>/dev/null');
    let text = p ? p.read('all') : '';
    if (p) p.close();
    return split(trim(text), ' ')[0] || '';
}
function package_fingerprint() {
    if (plan.manager != 'apk') return hash('/usr/lib/opkg/status');
    let p = popen('apk list -I --manifest 2>/dev/null | sort | sha256sum');
    let text = p ? p.read('all') : '';
    if (p) p.close();
    return split(trim(text), ' ')[0] || '';
}
function running(name) {
    let s = connect().call('service', 'list', { name });
    for (let key, item in (s?.[name]?.instances || {})) if (item.running) return true;
    return false;
}
function wait_confirmation() {
    state('verify'); log('Проверяю доступность API с панели; ожидаю подтверждение результата…');
    let seconds = min(90, max(5, int(message.verification_seconds || 90)));
    for (let n = 0; n < seconds; n++) {
        if (access(dir + '/confirmed')) return;
        sleep(1000);
    }
    die('Панель не подтвердила доступность. Выполняется восстановление.');
}
function restore_configs(saved, after, before_hash) {
    let ok = true;
    for (let path, content in saved) {
        if (before_hash[path] == hash(path)) continue;
        if (after[path] && after[path] == hash(path)) {
            put_file(path + '.bot4vps-restore', content, 0600);
            rename(path + '.bot4vps-restore', path);
        } else { ok = false; log('Происхождение изменения не подтверждено; не перезаписываю ' + path); }
    }
    return ok;
}
function package_names() {
    let p = popen(plan.manager == 'apk' ? 'apk list -I --manifest 2>/dev/null' : 'opkg list-installed 2>/dev/null');
    let output = p ? p.read('all') : '';
    if (p) p.close();
    let installed = map(split(output, '\n'), line => split(line, plan.manager == 'apk' ? ' ' : ' - ')[0]);
    return filter(['luci-i18n-podkop-ru', 'luci-app-podkop', 'podkop'], n => index(installed, n) >= 0);
}

let saved = {}, before_hash = {}, after = {}, before_running = running(message.service);
let before_enabled = length(glob('/etc/rc.d/S*' + message.service)) > 0;
let destructive = false, mutated = false, updating = message.action == 'update', binary_changes = {}, binary_backups = {};
function save_version() {
    let path = message.service == 'ssclash' ? plan.root + '/bin/ssclash' : message.service == 'adguardhome' ? plan.root + '/AdGuardHome' : null;
    command('mkdir -p /etc/bot4vps/services');
    put_file('/etc/bot4vps/services/' + message.service + '.json', sprintf('%J', { version: message.version, binary_sha256: path ? hash(path) : null }), 0600);
}
function save_binary(path, name) {
    if (!access(path)) return;
    let backup = dir + '/before-' + name;
    command('cp -p ' + quote(path) + ' ' + quote(backup));
    binary_backups[path] = backup;
}
function install_packages(files, rollback) {
    let packages = filter(files || [], item => item.role == 'package');
    if (!length(packages)) return;
    let list = join(' ', map(packages, item => quote(dir + '/' + item.name)));
    if (plan.manager == 'apk') {
        put_file(dir + '/apk.repositories', '', 0600);
        let apk = 'apk --root / --no-network --repositories-file ' + quote(dir + '/apk.repositories') + ' --allow-untrusted add --no-scripts ';
        let constraints = '';
        if (rollback) {
            for (let item in packages)
                if (!match(item.package || '', /^[A-Za-z0-9_.+-]+$/) || !match(item.version || '', /^[A-Za-z0-9_.+~:-]+$/)) die('В резерве APK нет точной версии пакета');
            constraints = ' ' + join(' ', map(packages, item => quote(item.package + '=' + item.version)));
            log('Возвращаю точные исходные версии APK и проверяю их зависимости…');
        }
        command(apk + '--simulate ' + list + constraints); command(apk + list + constraints);
    } else {
        put_file(dir + '/opkg.conf', 'dest root /\narch all 1\narch noarch 1\narch ' + plan.architecture + ' 10\nlists_dir ext ' + dir + '/lists\n', 0600);
        let opkg = 'opkg --offline-root / -f ' + quote(dir + '/opkg.conf') + (rollback ? ' --force-downgrade ' : ' ');
        command(opkg + '--noaction install ' + list); command(opkg + 'install ' + list);
    }
}
try {
    state('running');
    command('usign -V -p ' + quote('/etc/bot4vps/keys/' + username + '.pub') + ' -m ' + quote(dir + '/manifest.json') + ' -x ' + quote(dir + '/manifest.sig'));
    if (message.nonce != nonce || message.username != username || message.expected != plan.expected || message.service != plan.service || message.action != plan.action || time() > plan.expires)
        die('План операции не совпадает с подтверждённым');
    if (package_fingerprint() != plan.package_hash) die('Состав пакетов изменился после подтверждения');
    if (!match(message.service || '', /^(dnsmasq|podkop|ssclash|adguardhome)$/)) die('Служба не разрешена');
    if (!match(message.action || '', /^(start|stop|restart|remove|install|update|web_access)$/)) die('Операция не разрешена');
    if (message.action == 'remove' && message.service == 'dnsmasq') die('Системный dnsmasq удалять нельзя');
    if (updating && (before_running != plan.running || (plan.binary_path && hash(plan.binary_path) != plan.binary_hash))) die('Служба изменилась после просмотра плана');
    if (hash('/etc/init.d/' + message.service) != plan.init_hash) die('Служба изменилась после просмотра плана');
    if (message.service == 'adguardhome') {
        let info = agh.information();
        if ((message.action == 'stop' || message.action == 'remove') && length(info.dns_dependencies)) die('DNS зависит от AdGuard Home; сначала верните рабочие DNS-серверы');
        if (message.action == 'start' && !info.configured && info.setup_port_busy) die('TCP-порт 3000 занят');
    }
    for (let path in ['/etc/config/network', '/etc/config/dhcp', '/etc/config/firewall']) {
        let content = readfile(path);
        if (content != null) { saved[path] = content; before_hash[path] = hash(path); }
    }
    log('Сохраняю настройки сети до операции…');
    if (message.action == 'web_access') {
        let path = '/etc/config/ssclash';
        if (message.service != 'ssclash' || index(['lan', 'wan'], message.web_scope) < 0 || message.web_scope != plan.web_scope || hash(path) != plan.web_config_hash || !access(path)) die('План доступа SSClash изменился или конфигурация отсутствует');
        saved[path] = readfile(path); before_hash[path] = hash(path);
        mutated = true;
        command('uci set ssclash.main.web_scope=' + quote(message.web_scope) + ' && uci commit ssclash');
        after[path] = hash(path);
        if (before_running) command('/etc/init.d/ssclash restart');
        wait_confirmation(); state('success'); exit(0);
    }
    if (updating) {
        if (!access('/etc/init.d/' + message.service) || message.service == 'dnsmasq') die('Обновление службы не поддерживается');
        if (message.service == 'adguardhome' && !agh.information().managed) die('Принадлежность AdGuard Home не подтверждена');
        let config = message.service == 'podkop' ? '/etc/config/podkop' : message.service == 'adguardhome' ? plan.root + '/AdGuardHome.yaml' : null;
        if (config && access(config)) { saved[config] = readfile(config); before_hash[config] = hash(config); }
        for (let item in [...(message.files || []), ...(message.rollback_files || [])])
            if (!match(item.name || '', /^[a-zA-Z0-9_.+~-]+$/) || hash(dir + '/' + item.name) != item.sha256) die('Файл обновления или отката повреждён');
        if (message.service != 'podkop' && length(filter(message.files || [], item => item.role == message.service)) != 1) die('В комплекте нет единственного бинарного файла службы');
        if (message.service == 'podkop' && !length(message.rollback_files || [])) die('Пакеты отката не подготовлены');
        if (message.service == 'ssclash') { save_binary(plan.root + '/bin/ssclash', 'ssclash'); save_binary(plan.root + '/bin/clash', 'clash'); }
        if (message.service == 'adguardhome') save_binary(plan.root + '/AdGuardHome', 'adguardhome');
        let destination = '/root/bot4vps-backup/' + nonce;
        command('mkdir -p ' + quote(destination) + ' && chmod 700 ' + quote(destination));
        if (config && access(config)) command('cp -p ' + quote(config) + ' ' + quote(destination + '/service.config'));
        if (message.service == 'ssclash') {
            put_file(dir + '/backup-exclude', './bin\n./cache\n', 0600);
            command('tar -czf ' + quote(destination + '/ssclash-data.tar.gz') + ' -C ' + quote(plan.root) + ' -X ' + quote(dir + '/backup-exclude') + ' .');
        }
        log('Резерв конфигурации: ' + destination);
        mutated = true; command('/etc/init.d/' + message.service + ' stop');
        install_packages(message.files, false);
        command('/etc/init.d/' + message.service + (before_enabled ? ' enable' : ' disable'));
        for (let item in message.files) {
            let path = item.role == 'ssclash' ? plan.root + '/bin/ssclash' : item.role == 'mihomo' ? plan.root + '/bin/clash' : item.role == 'adguardhome' ? plan.root + '/AdGuardHome' : null;
            if (!path) continue;
            let incoming = path + '.bot4vps-update-' + nonce;
            command((item.role == 'mihomo' ? 'gzip -dc ' : 'cat ') + quote(dir + '/' + item.name) + ' > ' + quote(incoming) + ' && chmod 755 ' + quote(incoming) + ' && mv ' + quote(incoming) + ' ' + quote(path));
            binary_changes[path] = hash(path);
        }
        for (let path, content in saved) after[path] = hash(path);
        if (before_running) command('/etc/init.d/' + message.service + ' start');
        for (let path, content in saved) after[path] = hash(path);
        wait_confirmation(); save_version();
        log('Обновление подтверждено. Конфигурация и автозапуск сохранены.');
        state('success'); exit(0);
    }
    if (message.action == 'install') {
        if (access('/etc/init.d/' + message.service)) die('Служба уже установлена; повторная установка отключена');
        for (let item in (message.files || [])) {
            if (!match(item.name || '', /^[a-zA-Z0-9_.+~-]+$/) || hash(dir + '/' + item.name) != item.sha256)
                die('Файл комплекта повреждён или имя недопустимо');
        }
        let packages = filter(message.files, f => f.role == 'package');
        let list = join(' ', map(packages, f => quote(dir + '/' + f.name)));
        if (length(packages)) {
            log('Устанавливаю пакеты из локального комплекта; внешние источники не используются…');
            let arch = plan.architecture;
            if (!match(arch || '', /^[a-zA-Z0-9_-]+$/)) die('Архитектура не определена');
            log('Проверяю зависимости без применения изменений…');
            if (plan.manager == 'apk') {
                put_file(dir + '/apk.repositories', '', 0600);
                let apk = 'apk --root / --no-network --repositories-file ' + quote(dir + '/apk.repositories') + ' --allow-untrusted add --no-scripts ';
                command(apk + '--simulate ' + list);
                destructive = true;
                command(apk + list);
            } else {
                put_file(dir + '/opkg.conf', 'dest root /\narch all 1\narch noarch 1\narch ' + arch + ' 10\nlists_dir ext ' + dir + '/lists\n', 0600);
                command('opkg --offline-root / -f ' + quote(dir + '/opkg.conf') + ' --noaction install ' + list);
                destructive = true;
                command('opkg --offline-root / -f ' + quote(dir + '/opkg.conf') + ' install ' + list);
            }
        }
        if (message.service == 'adguardhome') {
            if (plan.root != '/opt/AdGuardHome' || access(plan.root)) die('Каталог AdGuard Home занят или изменился');
            let binaries = filter(message.files, f => f.role == 'adguardhome' && f.name == 'AdGuardHome');
            if (length(binaries) != 1) die('Ожидался один бинарный файл AdGuard Home');
            let info = agh.information();
            if (info.free_bytes == null || info.free_bytes < binaries[0].size + 16 * 1024 * 1024) die('Недостаточно места: нужен бинарный файл и не менее 16 МБ для данных. Подключите внешнее хранилище.');
            if (!match(plan.bind_address || '', /^[0-9.]+$/)) die('Не определён IPv4-адрес управления');
            let init = readfile('/usr/share/bot4vps/adguardhome.init'); if (!init) die('Компонент службы AdGuard Home отсутствует');
            destructive = true;
            command('mkdir -m 700 ' + quote(plan.root));
            command('cp ' + quote(dir + '/AdGuardHome') + ' ' + quote(plan.root + '/AdGuardHome') + ' && chmod 755 ' + quote(plan.root + '/AdGuardHome'));
            put_file('/etc/init.d/adguardhome', replace(init, 'BIND_ADDRESS', plan.bind_address), 0755);
            log('AdGuard Home установлен из GitHub-комплекта. Автозапуск выключен. DNS/DHCP и сеть не менялись. Откройте инструкцию настройки во вкладке «Пакеты».');
        }
        if (message.service == 'ssclash') {
            destructive = true;
            let root = plan.root;
            command('mkdir -p ' + quote(root + '/bin'));
            for (let item in message.files) {
                if (item.role == 'ssclash') command('cp ' + quote(dir + '/' + item.name) + ' ' + quote(root + '/bin/.ssclash-new') + ' && chmod 755 ' + quote(root + '/bin/.ssclash-new') + ' && mv ' + quote(root + '/bin/.ssclash-new') + ' ' + quote(root + '/bin/ssclash'));
                if (item.role == 'mihomo') command('gzip -dc ' + quote(dir + '/' + item.name) + ' > ' + quote(root + '/bin/.clash-new') + ' && chmod 755 ' + quote(root + '/bin/.clash-new') + ' && mv ' + quote(root + '/bin/.clash-new') + ' ' + quote(root + '/bin/clash'));
            }
            let init = readfile('/usr/share/bot4vps/ssclash.init');
            if (!init) die('Компонент службы SSClash отсутствует');
            if (!access('/etc/config/ssclash')) put_file('/etc/config/ssclash', "# Bot4VPS SSClash web access\nconfig ssclash 'main'\n\toption web_scope 'lan'\n\toption web_port '9091'\n", 0600);
            if (!access('/etc/init.d/ssclash')) put_file('/etc/init.d/ssclash', replace(init, 'ROOT=/opt/clash', 'ROOT=' + root), 0755);
        }
        log('Сервис установлен. Запуск и изменение маршрутизации выполняются отдельно.');
        save_version(); state('success'); exit(0);
    }
    if (message.action == 'remove') {
        mutated = true;
        log('Останавливаю ' + message.service + ' и очищаю его активные сетевые правила…');
        command('/etc/init.d/' + message.service + ' stop');
    } else {
        mutated = true;
        log('Выполняю ' + message.action + ' для ' + message.service + '…');
        command('/etc/init.d/' + message.service + ' ' + message.action);
    }
    for (let path, content in saved) after[path] = hash(path);
    wait_confirmation();
    if (message.action == 'remove') {
        if (message.service == 'adguardhome' && length(agh.information().dns_dependencies)) die('DNS изменился во время проверки; сначала верните рабочие upstream');
        log('Доступность подтверждена. Удаляю службу и принадлежащие ей файлы…');
        command('/etc/init.d/' + message.service + ' disable || ! /etc/init.d/' + message.service + ' enabled');
        if (message.keep_backup) {
            let destination = '/root/bot4vps-backup/' + nonce;
            command('mkdir -p ' + quote(destination) + ' && chmod 700 ' + quote(destination));
            if (message.service == 'ssclash') {
                put_file(dir + '/backup-exclude', './bin\n./cache\n', 0600);
                command('tar -czf ' + quote(destination + '/ssclash-data.tar.gz') + ' -C ' + quote(plan.root) + ' -X ' + quote(dir + '/backup-exclude') + ' .');
            }
            else if (message.service == 'adguardhome') { if (access(plan.root + '/AdGuardHome.yaml')) command('cp ' + quote(plan.root + '/AdGuardHome.yaml') + ' ' + quote(destination + '/AdGuardHome.yaml') + ' && chmod 600 ' + quote(destination + '/AdGuardHome.yaml')); }
            else if (access('/etc/config/podkop')) command('cp /etc/config/podkop ' + quote(destination + '/podkop.config') + ' && chmod 600 ' + quote(destination + '/podkop.config'));
            log('Резерв конфигурации: ' + destination);
        }
        destructive = true;
        if (message.service == 'ssclash') {
            if (index(readfile('/etc/init.d/ssclash') || '', '# Bot4VPS SSClash web access') >= 0 && index(readfile('/etc/config/ssclash') || '', '# Bot4VPS SSClash web access') >= 0) unlink('/etc/config/ssclash');
            command('rm -rf ' + quote(plan.root));
            unlink('/etc/init.d/ssclash');
            for (let path in glob('/etc/rc.d/*ssclash')) unlink(path);
        } else if (message.service == 'adguardhome') {
            if (plan.root != '/opt/AdGuardHome' || !agh.information().managed) die('Принадлежность службы не подтверждена');
            command('rm -rf ' + quote(plan.root)); unlink('/etc/init.d/adguardhome');
            for (let path in glob('/etc/rc.d/*adguardhome')) unlink(path);
        } else {
            let names = package_names();
            if (length(names)) {
                if (plan.manager == 'apk') {
                    put_file(dir + '/apk.repositories', '', 0600);
                    command('apk --root / --no-network --repositories-file ' + quote(dir + '/apk.repositories') + ' del --no-scripts ' + join(' ', map(names, quote)));
                } else command('opkg --offline-root / remove ' + join(' ', map(names, quote)));
            }
            for (let path in ['/etc/config/podkop', '/etc/config/podkop.opkg-save', '/etc/config/podkop.opkg-old', '/etc/config/podkop.opkg-new', '/etc/config/podkop.apk-new', '/etc/config/podkop.apk-save', '/etc/config/podkop.apk-old']) unlink(path);
            command('rm -rf /usr/lib/podkop /www/luci-static/resources/view/podkop');
            for (let path in glob('/tmp/podkop*')) { if (match(path, /^\/tmp\/podkop[a-zA-Z0-9_.-]*$/)) command('rm -rf ' + quote(path)); }
        }
        log('Системные зависимости сохранены. Другие службы и API-доступ не удалялись.');
    }
    state('success');
} catch (error) {
    log('Ошибка: ' + error);
    if (!mutated && !destructive) { state('failed', '' + error); exit(1); }
    if (updating) {
        try {
            command('/etc/init.d/' + message.service + ' stop');
            if (message.service == 'podkop') install_packages(message.rollback_files, true);
            for (let path, backup in binary_backups) {
                unlink(path + '.bot4vps-update-' + nonce);
                if (hash(path) == hash(backup)) continue;
                if (hash(path) != (binary_changes[path] || hash(backup))) die('Бинарный файл изменился параллельно; требуется ручная проверка');
                command('cp -p ' + quote(backup) + ' ' + quote(path + '.bot4vps-restore-' + nonce) + ' && mv ' + quote(path + '.bot4vps-restore-' + nonce) + ' ' + quote(path));
            }
            let restored = restore_configs(saved, after, before_hash);
            command('/etc/init.d/' + message.service + (before_enabled ? ' enable' : ' disable'));
            command('/etc/init.d/' + message.service + (before_running ? ' start' : ' stop'));
            state(restored ? 'rolled_back' : 'failed', '' + error);
            log(restored ? 'Восстановлена исходная версия службы и её конфигурация.' : 'Исходная версия восстановлена, но часть конфигурации требует ручной проверки.');
        } catch (restore_error) { state('failed', 'Откат обновления требует проверки: ' + restore_error); }
    } else if (!destructive) {
        let restored = restore_configs(saved, after, before_hash);
        try {
            if (before_enabled) command('/etc/init.d/' + message.service + ' enable');
            log('Восстанавливаю состояние ' + message.service + ': ' + (before_running ? 'start' : 'stop'));
            command('/etc/init.d/' + message.service + (before_running ? ' start' : ' stop'));
            state(restored ? 'rolled_back' : 'failed', '' + error);
            log(restored ? 'Предыдущее состояние службы восстановлено.' : 'Служба восстановлена, но часть настроек требует ручной проверки.');
        } catch (restore_error) { let detail = type(restore_error) == 'object' ? restore_error.message : '' + restore_error; log('Причина ошибки восстановления: ' + detail); state('failed', 'Восстановление не подтверждено: ' + detail); }
    } else state('failed', 'Изменение файлов или пакетов не завершено: ' + error + '. Проверьте журнал и подготовьте новый план.');
}
