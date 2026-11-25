#!/usr/bin/ucode
'use strict';
import { readfile, open, rename, popen } from 'fs';
import * as pm from '/usr/share/bot4vps/package-manager.uc';

let username = ARGV[0], nonce = ARGV[1];
if (!match(username || '', /^bot4vps_[a-f0-9]+$/) || !match(nonce || '', /^[a-f0-9]{32}$/)) exit(1);
let dir = '/tmp/bot4vps-jobs/' + username + '/' + nonce;
let plan = json(readfile(dir + '/plan.json') || '{}');
let message = json(readfile(dir + '/manifest.json') || '{}');
function quote(s) { return "'" + replace(s, "'", "'\\''") + "'"; }
function log(text) { let f = open(dir + '/log', 'a', 0600); if (f) { f.write(text + '\n'); f.close(); } }
function state(phase, error) {
    let f = open(dir + '/state.new', 'w', 0600);
    if (!f) die('Не удалось записать состояние установки');
    f.write(sprintf('%J', { phase, error: error || null, updated_at: time() })); f.close();
    rename(dir + '/state.new', dir + '/state.json');
}
function command(text) {
    let pipe = popen(text + ' 2>&1');
    if (!pipe) die('Не удалось запустить пакетный менеджер');
    let line;
    while ((line = pipe.read('line')) != null) log(trim(line));
    if (pipe.close() != 0) die('Пакетный менеджер завершился с ошибкой. Проверьте журнал.');
}
try {
    command('usign -V -p ' + quote('/etc/bot4vps/keys/' + username + '.pub') + ' -m ' + quote(dir + '/manifest.json') + ' -x ' + quote(dir + '/manifest.sig'));
    if (plan.kind != 'packages' || message.service != 'packages' || message.username != username || message.nonce != nonce || message.action != plan.action || message.expected != plan.expected || time() > plan.expires)
        die('План пакетов не совпадает с подтверждённым');
    if (pm.fingerprint() != plan.package_hash) die('Состав установленных пакетов изменился. Подготовьте новый план.');
    let inventory = pm.installed();
    state('running');
    if (plan.action == 'refresh') {
        log('Обновляю список доступных пакетов. Обновление установленных пакетов не запускается.');
        command(pm.manager() + ' update');
        if (pm.fingerprint() != plan.package_hash) die('Неожиданно изменился состав установленных пакетов');
    } else {
        if (plan.action != 'install' || !match(plan.package || '', /^[a-zA-Z0-9][a-zA-Z0-9_.+~-]{0,99}$/)) die('Установка не разрешена');
        if (pm.indexes_hash() != plan.indexes_hash) die('Список доступных пакетов изменился. Подготовьте новый план.');
        if (inventory[plan.package]) die('Пакет уже установлен');
        log('Повторно проверяю зависимости и отсутствие обновлений установленных пакетов…');
        if (pm.simulation(plan.package) != plan.simulation) die('План зависимостей изменился. Установка остановлена.');
        log('Устанавливаю ' + plan.package + ' из настроенных репозиториев роутера…');
        command(pm.manager() + (pm.manager() == 'apk' ? ' add ' : ' install ') + quote(plan.package));
        let after = pm.installed();
        if (!after[plan.package]) die('Установка выбранного пакета не подтверждена');
        for (let name, version in inventory) if (after[name] != version) die('Изменён ранее установленный пакет: ' + name + '. Проверьте журнал.');
        log('Выбранный пакет установлен. Версии ранее установленных пакетов сохранены.');
    }
    state('success');
} catch (error) {
    let detail = type(error) == 'object' ? error.message : '' + error;
    log(detail); state('failed', detail);
}
