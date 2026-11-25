'use strict';
import { readfile, popen, glob, access } from 'fs';

function quote(s) { return "'" + replace(s, "'", "'\\''") + "'"; }
function manager() { return access('/sbin/apk') || access('/usr/bin/apk') ? 'apk' : 'opkg'; }
function installed() {
    let pipe = popen(manager() == 'apk' ? 'apk list -I --manifest 2>/dev/null' : 'opkg list-installed 2>/dev/null');
    let output = pipe ? pipe.read('all') : '';
    if (pipe) pipe.close();
    let result = {};
    for (let line in split(output, '\n')) {
        let values = split(trim(line), manager() == 'apk' ? /\s+/ : ' - ');
        if (length(values) == 2) result[values[0]] = values[1];
    }
    return result;
}
function fingerprint() {
    let cmd = manager() == 'apk' ? 'apk list -I --manifest 2>/dev/null | sort | sha256sum' : 'sha256sum /usr/lib/opkg/status';
    let pipe = popen(cmd); let output = pipe ? pipe.read('all') : '';
    if (pipe) pipe.close();
    return split(trim(output), ' ')[0];
}
function indexes_hash() {
    let paths = manager() == 'apk' ? glob('/var/cache/apk/*') : glob('/var/opkg-lists/*');
    if (!length(paths)) return 'empty';
    let pipe = popen('sha256sum ' + join(' ', map(sort(paths), quote)) + ' 2>/dev/null | sha256sum');
    let output = pipe ? pipe.read('all') : '';
    if (pipe) pipe.close();
    return split(trim(output), ' ')[0];
}
function catalog(query, only_installed, offset) {
    query = lc(trim(query || ''));
    if (length(query) > 100 || match(query, /[[:cntrl:]]/) || index(query, '\x00') >= 0) die('Некорректный поиск пакетов');
    offset = min(100000, max(0, int(offset || 0)));
    let inventory = installed(), available = {};
    if (manager() == 'opkg') {
        // opkg handles its own list directory and compressed package indexes.
        let pipe = popen('opkg list 2>/dev/null');
        let output = pipe ? pipe.read('all') : '';
        if (pipe) pipe.close();
        for (let line in split(output, '\n')) {
            let parts = split(line, ' - ');
            if (length(parts) >= 2) available[parts[0]] = { name: parts[0], version: parts[1], description: length(parts) > 2 ? parts[2] : '' };
        }
    } else {
        // APK 3 query exposes name/version separately, including versions with dashes.
        let pipe = popen('apk query --from repositories --format json --fields name,version,description ' + quote('*') + ' 2>/dev/null');
        let output = pipe ? pipe.read('all') : '';
        let ok = pipe && pipe.close() == 0;
        if (ok && length(output)) {
            let value = json(output);
            let rows = type(value) == 'array' ? value : value.packages || value.results || [];
            for (let item in rows) if (item.name) available[item.name] = { name: item.name, version: item.version, description: item.description || '' };
        }
    }
    let has_indexes = length(available) > 0;
    for (let name, version in inventory) {
        if (!available[name]) available[name] = { name, version, description: '' };
        available[name].installed_version = version;
    }
    let names = filter(sort(keys(available)), name => (!only_installed || inventory[name] != null) &&
        (!length(query) || index(lc(name + ' ' + available[name].description), query) >= 0));
    let page = [];
    for (let i = offset; i < min(length(names), offset + 40); i++) push(page, available[names[i]]);
    return { manager: manager(), items: page,
        total: length(names), offset, has_indexes, installed_count: length(inventory), package_hash: fingerprint() };
}
function simulation(name) {
    if (!match(name || '', /^[a-zA-Z0-9][a-zA-Z0-9_.+~-]{0,99}$/)) die('Некорректное имя пакета');
    let cmd = manager() == 'apk' ? 'apk add --simulate ' : 'opkg --noaction install ';
    let pipe = popen(cmd + quote(name) + ' 2>&1');
    let output = pipe ? pipe.read('all') : '';
    if (!pipe || pipe.close() != 0) die('Не удалось рассчитать установку: ' + substr(output, -3000));
    if (match(output, /(Upgrading|Downgrading|Reinstalling|Removing|Purging|Replacing)/i))
        die('Установка требует изменения существующих пакетов. Автоматическая замена отключена; выберите совместимый пакет.');
    return output;
}
function prepare(action, data) {
    if (action != 'refresh' && action != 'install') die('Действие пакетного менеджера не поддерживается');
    let inventory = installed();
    let plan = { service: 'packages', kind: 'packages', action, manager: manager(),
        package_hash: fingerprint(), indexes_hash: indexes_hash(), expires: time() + 900,
        package: data.package || '', summary: [] };
    if (action == 'refresh') plan.summary = ['Обновить список доступных пакетов. Установленные пакеты не обновляются.'];
    else {
        if (inventory[plan.package]) die('Пакет уже установлен. Переустановка и обновление не выполняются.');
        let output = simulation(plan.package);
        plan.simulation = output;
        plan.summary = filter(split(output, '\n'), line => length(trim(line)) > 0);
        if (!length(plan.summary)) die('Пакетный менеджер не подтвердил установку');
    }
    plan.expected = plan.package_hash + ':' + plan.indexes_hash + ':' + plan.package;
    return plan;
}
export { manager, installed, fingerprint, indexes_hash, catalog, simulation, prepare };
