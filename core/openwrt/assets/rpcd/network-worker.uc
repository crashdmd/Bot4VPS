#!/usr/bin/ucode
'use strict';
import { readfile, open, access, rename, popen } from 'fs';
import { connect } from 'ubus';
import * as config from '/usr/share/bot4vps/configuration.uc';

let username = ARGV[0], nonce = ARGV[1];
if (!match(username || '', /^bot4vps_[a-f0-9]+$/) || !match(nonce || '', /^[a-f0-9]{32}$/)) exit(1);
let dir = '/tmp/bot4vps-jobs/' + username + '/' + nonce;
let plan = json(readfile(dir + '/plan.json') || '{}');
let message = json(readfile(dir + '/manifest.json') || '{}');
function quote(s) { return "'" + replace(s, "'", "'\\''") + "'"; }
function put(path, content) {
    let file = open(path, 'w', 0600);
    if (!file) die('Не удалось сохранить состояние сетевой операции');
    file.write(content); file.close();
}
function log(text) {
    let file = open(dir + '/log', 'a', 0600);
    if (file) { file.write(text + '\n'); file.close(); }
}
function state(phase, error) {
    put(dir + '/state.new', sprintf('%J', { phase, error: error || null, updated_at: time() }));
    rename(dir + '/state.new', dir + '/state.json');
}
function hash(path) {
    let pipe = popen('sha256sum ' + quote(path) + ' 2>/dev/null');
    let output = pipe ? pipe.read('all') : '';
    if (pipe) pipe.close();
    return split(trim(output), ' ')[0] || '';
}
function command(text) {
    let pipe = popen(text + ' 2>&1');
    if (!pipe) die('Не удалось запустить сетевой шаг');
    let line;
    while ((line = pipe.read('line')) != null) log(trim(line));
    if (pipe.close() != 0) die('Сетевой шаг завершился с ошибкой');
}
function swap(config, source, expected) {
    if (hash(dir + '/' + source) != expected) die('Снимок конфигурации повреждён');
    put('/etc/config/' + config + '.bot4vps-new', readfile(dir + '/' + source));
    if (!rename('/etc/config/' + config + '.bot4vps-new', '/etc/config/' + config)) die('Не удалось применить конфигурацию');
}
function action(name, method) {
    if (!match(name || '', /^[a-zA-Z][a-zA-Z0-9_]{0,30}$/) || name == 'loopback') die('Интерфейс не разрешён');
    let result = connect().call('network.interface.' + name, method, {});
    if (result == null) die('netifd не подтвердил действие ' + method);
}
let changed = false;
try {
    command('usign -V -p ' + quote('/etc/bot4vps/keys/' + username + '.pub') + ' -m ' + quote(dir + '/manifest.json') + ' -x ' + quote(dir + '/manifest.sig'));
    if (plan.kind != 'network' || message.service != 'network' || message.username != username || message.nonce != nonce || message.action != plan.action || message.expected != plan.expected || time() > plan.expires)
        die('Сетевой план не совпадает с подтверждённым');
    if (hash('/etc/config/network') != plan.before_hash) die('Сеть изменилась после просмотра плана');
    if (plan.uhttpd_before && hash('/etc/config/uhttpd') != plan.uhttpd_before) die('Настройки HTTPS изменились после просмотра плана');
    if (plan.settings_before && config.fingerprint() != plan.settings_before) die('Конфигурация изменилась после просмотра плана');
    for (let item in plan.configs || []) {
        if (index(['dhcp', 'firewall', 'wireless'], item.name) < 0 || hash('/etc/config/' + item.name) != item.before || hash(dir + '/' + item.name + '.before') != item.before || hash(dir + '/' + item.name + '.after') != item.after) die('Снимок конфигурации изменился');
    }
    state('running');
    log('План проверен. При отсутствии подтверждения роутер самостоятельно восстановит предыдущее состояние.');
    if (plan.configs) {
        changed = true;
        for (let item in plan.configs) swap(item.name, item.name + '.after', item.after);
        if (plan.reload == 'firewall') { command('fw4 check'); command('/etc/init.d/firewall restart'); }
        else if (plan.reload == 'dnsmasq') command('/etc/init.d/dnsmasq restart');
        else if (plan.reload == 'wireless') command('/sbin/wifi reload');
        else die('Служба применения не разрешена');
    } else if (plan.action == 'up' || plan.action == 'down' || plan.action == 'reconnect') {
        changed = true;
        log('netifd: ' + plan.interface + ' / ' + plan.action);
        if (plan.action == 'reconnect') { action(plan.interface, 'down'); sleep(1000); action(plan.interface, 'up'); }
        else action(plan.interface, plan.action);
    } else {
        if (index(['edit', 'delete', 'routes'], plan.action) < 0) die('Сетевое действие не разрешено');
        if (hash(dir + '/network.before') != plan.before_hash || hash(dir + '/network.after') != plan.after_hash) die('Снимок UCI повреждён');
        log('Применяю подготовленные изменения UCI…');
        changed = true;
        swap('network', 'network.after', plan.after_hash);
        if (plan.uhttpd_after) swap('uhttpd', 'uhttpd.after', plan.uhttpd_after);
        command('/etc/init.d/network reload');
        if (plan.uhttpd_after) { log('Переношу HTTPS на новый адрес LAN…'); command('/etc/init.d/uhttpd reload'); }
    }
    state('verify');
    log('Ожидаю проверку конфигурации и доступности API с панели…');
    let seconds = min(120, max(5, int(message.verification_seconds || 120)));
    for (let i = 0; i < seconds; i++) {
        if (access(dir + '/confirmed')) { log('Конфигурация и доступность подтверждены.'); state('success'); exit(0); }
        sleep(1000);
    }
    die('Панель не подтвердила доступность. Возвращаю прежнюю конфигурацию.');
} catch (error) {
    let detail = type(error) == 'object' ? error.message : '' + error;
    log(detail);
    if (!changed) { state('failed', detail); exit(1); }
    try {
        if (plan.configs) {
            for (let item in plan.configs) {
                let current = hash('/etc/config/' + item.name);
                if (current != item.after && current != item.before) die('Конфигурация изменена параллельно; чужие изменения не перезаписываются');
            }
            for (let item in plan.configs) swap(item.name, item.name + '.before', item.before);
            if (plan.reload == 'firewall') command('/etc/init.d/firewall restart');
            else if (plan.reload == 'wireless') command('/sbin/wifi reload');
            else command('/etc/init.d/dnsmasq restart');
        } else if (plan.action == 'up' || plan.action == 'down' || plan.action == 'reconnect') {
            if (hash('/etc/config/network') != plan.before_hash) die('Сеть изменена параллельно; требуется ручная проверка');
            action(plan.interface, plan.previous_up ? 'up' : 'down');
        } else {
            let current = hash('/etc/config/network');
            if (current != plan.after_hash && current != plan.before_hash) die('Сеть изменена параллельно; чужие изменения не перезаписываются');
            swap('network', 'network.before', plan.before_hash);
            if (plan.uhttpd_before) {
                let https = hash('/etc/config/uhttpd');
                if (https != plan.uhttpd_after && https != plan.uhttpd_before) die('HTTPS изменён параллельно; требуется ручная проверка');
                swap('uhttpd', 'uhttpd.before', plan.uhttpd_before);
            }
            command('/etc/init.d/network reload');
            if (plan.uhttpd_before) command('/etc/init.d/uhttpd reload');
        }
        log('Прежняя конфигурация восстановлена роутером.'); state('rolled_back', detail);
    } catch (failure) {
        let reason = type(failure) == 'object' ? failure.message : '' + failure;
        log('Ошибка восстановления: ' + reason); state('failed', 'Восстановление не подтверждено: ' + reason);
    }
}
