'use strict';
import { readfile, open, stat, lstat, glob, popen, unlink, rename } from 'fs';

let username = ARGV[0], nonce = ARGV[1], name = ARGV[2], size = int(ARGV[3]), expected_hash = ARGV[4];
function quote(s) { return "'" + replace(s, "'", "'\\''") + "'"; }
if (!match(username || '', /^bot4vps_[a-f0-9]+$/) || !match(nonce || '', /^[a-f0-9]{32}$/) ||
    !match(name || '', /^[a-zA-Z0-9_.+~-]+$/) || name == '.' || name == '..' || match(name, /\.ssh-part$/) ||
    !match(expected_hash || '', /^[a-f0-9]{64}$/) || size <= 0 || size > 128 * 1024 * 1024)
    die('Некорректный файл');
let dir = '/tmp/bot4vps-jobs/' + username + '/' + nonce;
for (let path in ['/tmp/bot4vps-jobs', '/tmp/bot4vps-jobs/' + username, dir])
    if (lstat(path)?.type != 'directory') die('Каталог подготовленного плана не найден');
let state = json(readfile(dir + '/state.json') || '{}');
let plan = json(readfile(dir + '/plan.json') || '{}');
if (state.phase != 'prepared') die('Операция не ожидает файлы');
if (!plan.expires || time() > plan.expires) die('План операции истёк');
let limit = name == 'manifest.json' ? 65536 : name == 'manifest.sig' ? 1024 : 0;
if (!limit) {
    if (match(name, /^(plan\.json|state\.json|state\.new|log|confirmed|opkg\.conf|apk\.repositories|backup-exclude|before-(ssclash|clash|adguardhome)|(network|uhttpd|dhcp|firewall)\.(before|after))$/))
        die('Имя файла зарезервировано');
    let signature = popen('usign -V -p ' + quote('/etc/bot4vps/keys/' + username + '.pub') +
        ' -m ' + quote(dir + '/manifest.json') + ' -x ' + quote(dir + '/manifest.sig') + ' >/dev/null 2>&1');
    if (!signature || signature.close() != 0) die('Сначала передайте подписанный план');
    let manifest = json(readfile(dir + '/manifest.json') || '{}');
    if (manifest.username != username || manifest.nonce != nonce || manifest.expected != plan.expected ||
        manifest.service != plan.service || manifest.action != plan.action || time() > manifest.expires)
        die('Подписанный план не соответствует операции');
    for (let file in [...(manifest.files || []), ...(manifest.rollback_files || [])])
        if (file.name == name && file.sha256 == expected_hash && int(file.size) == size) limit = int(file.size);
}
if (!limit || size > limit) die('Файл отсутствует в подписанном плане или превышает лимит');
let target = dir + '/' + name, before = lstat(target), temporary = target + '.ssh-part', partial = lstat(temporary);
if (before && before.type != 'file') die('Путь файла занят');
if (partial) die('Предыдущая передача файла ещё не завершена');
let total = 0;
for (let path in glob('/tmp/bot4vps-jobs/*/*/*')) total += stat(path)?.size || 0;
if (total + size > 128 * 1024 * 1024) die('Общий лимит временных файлов исчерпан');
let source = open('/dev/stdin', 'r'), destination = open(temporary, 'w', 0600);
if (!source || !destination) die('Не удалось открыть файл передачи');
print('READY\n');
let done = 0, chunk;
function failed(message) { destination.close(); source.close(); unlink(temporary); die(message); }
while ((chunk = source.read(256 * 1024)) != null && length(chunk)) {
    if (done + length(chunk) > size) failed('Передано больше данных, чем разрешено');
    if (destination.write(chunk) != length(chunk)) failed('Не удалось сохранить файл');
    done += length(chunk);
}
destination.close(); source.close();
if (done != size) { unlink(temporary); die('Передача файла не завершена'); }
let pipe = popen('sha256sum ' + quote(temporary) + ' 2>/dev/null');
let hash = split(trim(pipe ? pipe.read('all') : ''), ' ')[0];
if (!pipe || pipe.close() != 0 || hash != expected_hash) { unlink(temporary); die('Контрольная сумма переданного файла не совпала'); }
state = json(readfile(dir + '/state.json') || '{}');
if (state.phase != 'prepared' || time() > plan.expires) { unlink(temporary); die('План операции больше не ожидает файлы'); }
if (!rename(temporary, target)) { unlink(temporary); die('Не удалось сохранить файл'); }
print(sprintf('%J\n', { ok: true, size: done, sha256: hash }));
