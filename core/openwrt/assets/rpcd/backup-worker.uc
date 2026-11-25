#!/usr/bin/ucode
'use strict';
import { readfile, open, rename, popen, access, stat, lstat, realpath } from 'fs';
import { connect } from 'ubus';
import * as backup from '/usr/share/bot4vps/backup.uc';

let username = ARGV[0], nonce = ARGV[1];
if (!match(username || '', /^bot4vps_[a-f0-9]+$/) || !match(nonce || '', /^[a-f0-9]{32}$/)) exit(1);
let dir = '/tmp/bot4vps-jobs/' + username + '/' + nonce;
let plan = json(readfile(dir + '/plan.json') || '{}'), message = json(readfile(dir + '/manifest.json') || '{}');
function quote(value) { return "'" + replace(value, "'", "'\\''") + "'"; }
function log(text) { let file = open(dir + '/log', 'a', 0600); if (file) { file.write(text + '\n'); file.close(); } }
function state(phase, extra) {
    let file = open(dir + '/state.new', 'w', 0600); if (!file) die('Не удалось сохранить состояние копии');
    file.write(sprintf('%J', {phase, boot_id: trim(readfile('/proc/sys/kernel/random/boot_id') || ''), ...(extra || {}), updated_at: time()})); file.close();
    if (!rename(dir + '/state.new', dir + '/state.json')) die('Не удалось сохранить состояние копии');
}
function command(text) {
    let pipe = popen(text + ' 2>&1'); if (!pipe) die('Не удалось запустить шаг резервного копирования');
    let line; while ((line = pipe.read('line')) != null) log(trim(line));
    if (pipe.close() != 0) die('Шаг резервного копирования завершился с ошибкой');
}
function hash(path) {
    let pipe = popen('sha256sum ' + quote(path)); let output = pipe ? pipe.read('all') : ''; if (pipe) pipe.close();
    return split(trim(output), ' ')[0] || '';
}
try {
    command('usign -V -p ' + quote('/etc/bot4vps/keys/' + username + '.pub') + ' -m ' + quote(dir + '/manifest.json') + ' -x ' + quote(dir + '/manifest.sig'));
    if (plan.kind != 'backup' || message.service != 'backup' || message.username != username || message.nonce != nonce || message.action != plan.action || message.expected != plan.expected || time() > plan.expires || time() > message.expires)
        die('План копии не совпадает с подтверждённым');
    let expected = plan.before_hash + (plan.action == 'restore' ? ':' + plan.archive_sha256 + ':' + plan.archive_size : '');
    if (plan.expected != expected) die('Параметры подтверждённого архива изменились');
    if (plan.action == 'restore') {
        let files = message.files || [];
        if (length(files) != 1 || files[0].name != 'restore.tar.gz' || files[0].sha256 != plan.archive_sha256 || files[0].size != plan.archive_size)
            die('Архив не совпадает с подписанным планом');
    }
    if (backup.fingerprint() != plan.before_hash) die('Настройки изменились после просмотра плана');
    state('running');
    if (plan.action == 'create') {
        log('Создаю штатный архив настроек OpenWrt…');
        command('umask 077; /sbin/sysupgrade -b ' + quote(dir + '/backup.tar.gz'));
        let size = stat(dir + '/backup.tar.gz')?.size || 0;
        if (size <= 0 || size > 32 * 1024 * 1024) die('Размер копии превышает допустимые 32 МБ');
        command('gzip -t ' + quote(dir + '/backup.tar.gz'));
        log('Архив создан. Ожидаю сохранение на панели.');
        state('success', {archive: {size, sha256: hash(dir + '/backup.tar.gz')}});
    } else if (plan.action == 'restore') {
        let path = dir + '/restore.tar.gz';
        if ((stat(path)?.size || 0) != plan.archive_size || hash(path) != plan.archive_sha256) die('Архив восстановления повреждён');
        command('gzip -t ' + quote(path));
        let listing = popen('tar -tzf ' + quote(path)), listed = {}, line;
        if (!listing) die('Не удалось проверить состав архива');
        while ((line = listing.read('line')) != null) {
            let name = replace(replace(replace(line, /\n$/, ''), /^(\.\/)+/, ''), /\/$/, '');
            if (name == '.' || name == '') continue;
            if (listed[name] || !length(filter(plan.entries, entry => entry.path == name))) die('Состав архива не совпадает с подтверждённым планом');
            listed[name] = true;
        }
        if (listing.close() != 0 || length(keys(listed)) != length(plan.entries)) die('Состав архива не совпадает с подтверждённым планом');
        for (let entry in plan.entries) {
            let parts = split(entry.path, '/'), prefix = '';
            for (let i = 0; i < length(parts); i++) {
                prefix += '/' + parts[i]; let info = lstat(prefix);
                if (info?.type == 'link' && (i < length(parts) - 1 || entry.type != 'link')) die('Путь восстановления проходит через существующую ссылку: ' + prefix);
            }
        }
        log('Архив и пути проверены. Восстанавливаю настройки штатным механизмом OpenWrt…');
        command('/sbin/sysupgrade -r ' + quote(path));
        log('Файлы восстановлены. Для применения настроек требуется отдельная перезагрузка.');
        state('success');
    } else if (plan.action == 'reboot') {
        log('Перезагрузка подтверждена. Адрес и доступ после запуска определяются восстановленными настройками.');
        state('success'); sleep(5000); connect().call('system', 'reboot', {});
    } else die('Действие копии не разрешено');
} catch (error) {
    let message = type(error) == 'object' ? error.message : '' + error;
    log(message); state('failed', {error: message}); exit(1);
}
