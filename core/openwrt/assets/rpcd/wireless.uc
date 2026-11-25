'use strict';
import { readfile, open, popen, mkdir, access } from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';

let radio_fields = ['disabled', 'channel', 'country', 'txpower', 'htmode'];
let iface_fields = ['disabled', 'ssid', 'encryption', 'hidden', 'isolate', 'network'];
function quote(value) { return "'" + replace(value, "'", "'\\''") + "'"; }
function hash(path) {
    let p = popen('sha256sum ' + quote(path) + ' 2>/dev/null');
    let text = p ? p.read('all') : ''; if (p) p.close();
    return split(trim(text), ' ')[0] || '';
}
function put(path, content) {
    let f = open(path, 'w', 0600); if (!f) die('Не удалось сохранить Wi-Fi');
    f.write(content); f.close();
}
function fields(s, names) { let out = {}; for (let n in names) if (s[n] != null) out[n] = s[n]; return out; }
function configuration() {
    let c = cursor(), bus = connect(), radios = [], networks = [];
    let runtime = bus ? bus.call('network.wireless', 'status', {}) : {};
    c.foreach('network', 'interface', s => { if (s['.name'] != 'loopback') push(networks, s['.name']); });
    c.foreach('wireless', 'wifi-device', function(s) {
        let name = s['.name'], state = runtime?.[name] || {};
        // iwinfo is another plugin in this rpcd process. A synchronous call
        // to it here blocks rpcd waiting for its own response.
        let radio = { name, band: s.band || (s.hwmode == '11a' ? '5g' : s.hwmode == '11g' ? '2g' : null),
            ...fields(s, radio_fields), up: !!state.up, pending: !!state.pending, interfaces: [],
            htmodes: [], frequencies: [] };
        c.foreach('wireless', 'wifi-iface', function(i) {
            if (i.device != name) return;
            let live = filter(state.interfaces || [], v => v.section == i['.name'])[0];
            push(radio.interfaces, { id: i['.name'], mode: i.mode, ...fields(i, iface_fields), has_key: !!i.key, ifname: live?.ifname });
        });
        push(radios, radio);
    });
    return { config_hash: hash('/etc/config/wireless'), radios, networks };
}
function survey(device) {
    let binary = access('/usr/sbin/iw') ? '/usr/sbin/iw' : access('/usr/bin/iw') ? '/usr/bin/iw' : null;
    if (!binary || !match(device || '', /^[a-zA-Z0-9_.-]{1,64}$/)) return [];
    let p = popen(binary + ' dev ' + quote(device) + ' survey dump 2>/dev/null');
    let text = p ? p.read('all') : ''; if (p) p.close();
    let rows = [], row = null;
    for (let line in split(text, '\n')) {
        let m = match(line, /frequency:\s*([0-9]+)/);
        if (m) { row = { frequency: int(m[1]), in_use: index(line, '[in use]') >= 0 }; push(rows, row); }
        if (!row) continue;
        m = match(line, /noise:\s*(-?[0-9]+)/); if (m) row.noise = int(m[1]);
        m = match(line, /channel active time:\s*([0-9]+)/); if (m) row.active_ms = int(m[1]);
        m = match(line, /channel busy time:\s*([0-9]+)/); if (m) row.busy_ms = int(m[1]);
    }
    return rows;
}
function measurement(name) {
    if (!match(name || '', /^[a-zA-Z0-9_]{1,64}$/) || cursor().get('wireless', name) != 'wifi-device') die('Радиомодуль не найден');
    let radio = filter(configuration().radios, r => r.name == name)[0];
    if (!radio.up) die('Для сканирования включите радиомодуль Wi-Fi');
    let device = filter(radio.interfaces, i => i.ifname)[0]?.ifname;
    return { survey: survey(device) };
}
function set_fields(c, id, values, allowed) {
    if (type(values) != 'object') die('Некорректные поля Wi-Fi');
    for (let key, value in values) {
        if (index(allowed, key) < 0) die('Поле Wi-Fi не поддерживается');
        if (value != null) {
            let items = type(value) == 'array' ? value : [value];
            if (length(items) > 32) die('Слишком много значений Wi-Fi');
            for (let item in items) if (type(item) != 'string' || length(item) > 256 || match(item, /[[:cntrl:]]/)) die('Некорректное значение Wi-Fi');
        }
        if (value == null || (type(value) == 'array' && !length(value))) c.delete('wireless', id, key);
        else c.set('wireless', id, key, value);
    }
}
function prepare(dir, data) {
    let original = configuration();
    if (data.config_hash != original.config_hash) die('Wi-Fi изменён. Обновите форму и проверьте изменения заново.');
    let radio = filter(original.radios, r => r.name == data.radio)[0];
    if (!radio) die('Радиомодуль не найден');
    // The panel checks iwinfo channel/mode support before requesting this plan.
    mkdir(dir + '/uci', 0700); mkdir(dir + '/delta', 0700);
    put(dir + '/wireless.before', readfile('/etc/config/wireless')); put(dir + '/uci/wireless', readfile('/etc/config/wireless'));
    let c = cursor(dir + '/uci', dir + '/delta');
    let plan = { service: 'network', kind: 'network', action: 'wireless', radio: data.radio, configs: [], reload: 'wireless',
        before_hash: hash('/etc/config/network'), summary: ['Перенастроить Wi-Fi ' + data.radio + '. Беспроводные клиенты временно потеряют соединение.'], expires: time() + 900 };
    set_fields(c, data.radio, data.settings || {}, radio_fields);
    for (let key, value in data.settings || {}) push(plan.summary, data.radio + ' / ' + key + ': ' + (value == null ? 'по умолчанию' : value));
    for (let iface in data.interfaces || []) {
        if (c.get('wireless', iface.id) != 'wifi-iface' || c.get('wireless', iface.id, 'device') != data.radio) die('Сеть не принадлежит выбранному радиомодулю');
        let settings = { ...iface.settings }, enc = settings.encryption || c.get('wireless', iface.id, 'encryption') || 'none';
        if (settings.encryption == 'none') settings.key = null;
        if (index(['none', 'psk2', 'psk2+ccmp', 'psk-mixed', 'sae', 'sae-mixed', 'sae+ccmp', 'sae-mixed+ccmp'], enc) < 0 && (settings.encryption != null || settings.key != null)) die('Расширенная защита Wi-Fi редактируется в LuCI');
        if (substr(enc, 0, 3) == 'sae' && length(settings.key || c.get('wireless', iface.id, 'key') || '') > 63) die('Для WPA3 укажите новый пароль длиной не более 63 байт');
        if (enc != 'none' && !settings.key && !c.get('wireless', iface.id, 'key')) die('Укажите пароль защищённой сети Wi-Fi');
        for (let net in settings.network || []) if (cursor().get('network', net) != 'interface' || net == 'loopback') die('Сеть подключения Wi-Fi не найдена');
        set_fields(c, iface.id, settings, [...iface_fields, 'key']);
        for (let key, value in settings) push(plan.summary, iface.id + ' / ' + key + ': ' + (key == 'key' ? value == null ? 'удалить пароль' : 'новое скрытое значение' : value == null ? 'по умолчанию' : type(value) == 'array' ? join(', ', value) : value));
    }
    if (!c.commit('wireless')) die('Не удалось подготовить Wi-Fi');
    put(dir + '/wireless.after', readfile(dir + '/uci/wireless'));
    push(plan.configs, { name: 'wireless', before: original.config_hash, after: hash(dir + '/wireless.after') });
    plan.expected = original.config_hash + ':' + plan.configs[0].after + ':wireless';
    return plan;
}
export { configuration, measurement, prepare };
