'use strict';
import { readfile, open, access, popen, glob, mkdir, unlink } from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
import * as config from '/usr/share/bot4vps/configuration.uc';
import * as wifi from '/usr/share/bot4vps/wireless.uc';

function quote(value) { return "'" + replace(value, "'", "'\\''") + "'"; }
function digest(path) {
    let pipe = popen('sha256sum ' + quote(path) + ' 2>/dev/null');
    let output = pipe ? pipe.read('all') : '';
    if (pipe) pipe.close();
    return split(trim(output), ' ')[0] || '';
}
function put(path, data) {
    let file = open(path, 'w', 0600);
    if (!file) die('Не удалось сохранить сетевой план');
    file.write(data); file.close();
}
let interface_fields = ['proto', 'device', 'ipaddr', 'netmask', 'gateway', 'dns', 'metric', 'mtu',
    'defaultroute', 'peerdns', 'auto', 'username', 'addresses', 'listen_port', 'ip6addr', 'ip6gw'];
let peer_fields = ['public_key', 'endpoint_host', 'endpoint_port', 'allowed_ips', 'persistent_keepalive', 'route_allowed_ips', 'description'];
let route_fields = ['interface', 'target', 'netmask', 'gateway', 'metric', 'table', 'onlink'];
function fields(section, names) {
    let result = {};
    for (let name in names) if (section[name] != null) result[name] = section[name];
    return result;
}
function configuration() {
    let c = cursor(), interfaces = [], routes = [];
    let bus = connect(), state = bus ? bus.call('network.interface', 'dump', {}) : {};
    c.foreach('network', 'interface', function(s) {
        let iface = { name: s['.name'], ...fields(s, interface_fields),
            has_password: !!s.password, has_private_key: !!s.private_key, peers: [] };
        if (type(iface.ipaddr) == 'string' && index(iface.ipaddr, '/') >= 0) {
            let parts = split(iface.ipaddr, '/');
            let prefix = int(parts[1]);
            if (length(parts) == 2 && prefix >= 0 && prefix <= 32) {
                iface.ipaddr = parts[0];
                if (!iface.netmask) {
                    let octets = [];
                    for (let i = 0; i < 4; i++) {
                        let bits = min(8, max(0, prefix - i * 8));
                        push(octets, bits == 0 ? 0 : 256 - (1 << (8 - bits)));
                    }
                    iface.netmask = join('.', octets);
                }
            }
        }
        for (let current in (state?.interface || []))
            if (current.interface == s['.name']) {
                iface.up = !!current.up; iface.pending = !!current.pending;
                iface.runtime_device = current.l3_device || current.device || iface.device;
                iface.runtime_addresses = map(current['ipv4-address'] || [], ip => ip.address);
            }
        if (s.proto == 'wireguard') c.foreach('network', 'wireguard_' + s['.name'], function(peer) {
            push(iface.peers, { ...fields(peer, peer_fields), id: peer['.name'], has_preshared_key: !!peer.preshared_key });
        });
        if (s['.name'] != 'loopback') push(interfaces, iface);
    });
    c.foreach('network', 'route', function(s) { push(routes, { id: s['.name'], ...fields(s, route_fields) }); });
    let devices = bus ? bus.call('network.device', 'status', {}) : {};
    let names = keys(devices || {});
    for (let path in glob('/sys/class/net/*')) {
        let parts = split(path, '/'); let name = parts[length(parts) - 1];
        if (name != 'lo' && index(names, name) < 0) push(names, name);
    }
    c.foreach('network', 'device', function(s) { if (s.name && index(names, s.name) < 0) push(names, s.name); });
    return { ...config.configuration(), interfaces, routes, devices: sort(names), config_hash: digest('/etc/config/network') };
}
function validate_fields(settings, allowed) {
    if (type(settings) != 'object') die('Некорректные поля интерфейса');
    for (let name, value in settings) {
        if (index(allowed, name) < 0) die('Поле сети не поддерживается: ' + name);
        if (value == null) continue;
        let values = type(value) == 'array' ? value : [value];
        if (length(values) > 32) die('Слишком много значений сетевого поля');
        for (let item in values)
            if (type(item) != 'string' || length(item) > 256 || match(item, /[[:cntrl:]]/) || index(item, '\x00') >= 0)
                die('Недопустимое значение сетевого поля');
    }
}
function set_fields(c, config, section, settings) {
    for (let key, value in settings) {
        if (value == null || value == '' || (type(value) == 'array' && !length(value))) c.delete(config, section, key);
        else c.set(config, section, key, value);
    }
}
function prepare(dir, action, data) {
    if (action == 'wireless') return wifi.prepare(dir, data);
    if (index(['dhcp', 'dns', 'firewall', 'firewall_restart'], action) >= 0) return config.prepare(dir, action, data);
    let original = configuration();
    if (data.config_hash != original.config_hash) die('Сеть изменилась после открытия формы. Обновите данные и проверьте изменения.');
    let name = data.interface;
    if (action != 'routes' && !match(name || '', /^[a-zA-Z][a-zA-Z0-9_]{0,30}$/)) die('Некорректное имя интерфейса');
    if (name == 'loopback') die('Изменение loopback не поддерживается');
    let current = null;
    for (let item in original.interfaces) if (item.name == name) current = item;
    if (action != 'edit' && action != 'routes' && !current) die('Интерфейс не найден');
    let api_addresses = data.api_addresses || [data.api_host];
    let management = current && (index(api_addresses,current.ipaddr) >= 0 || length(filter(current.runtime_addresses || [], ip => index(api_addresses,ip) >= 0)) > 0);
    let before = digest('/etc/config/network');
    let expected = before;
    let plan = { service: 'network', kind: 'network', action, interface: name || '', before_hash: before,
        previous_up: !!current?.up, api_host: data.api_host, new_api_host: data.api_host,
        summary: [], expires: time() + 900 };
    if (action == 'up' || action == 'down' || action == 'reconnect') {
        if (action == 'down' && current.proto == 'static' && management)
            die('Интерфейс доступа к панели нельзя отключить. Используйте редактирование с откатом.');
        plan.summary = [name + ': ' + (action == 'up' ? 'подключить' : action == 'down' ? 'отключить' : 'переподключить')];
    } else {
        if (index(['edit', 'delete', 'routes'], action) < 0) die('Сетевое действие не поддерживается');
        mkdir(dir + '/uci', 0700);
        mkdir(dir + '/delta', 0700);
        put(dir + '/network.before', readfile('/etc/config/network'));
        put(dir + '/uci/network', readfile('/etc/config/network'));
        let c = cursor(dir + '/uci', dir + '/delta');
        if (action == 'routes') {
            if (type(data.routes) != 'array' || length(data.routes) > 64) die('Некорректный список маршрутов');
            let names = [];
            c.foreach('network', 'route', function(s) { push(names, s['.name']); });
            for (let id in names) c.delete('network', id);
            for (let route in data.routes) {
                validate_fields(route, route_fields);
                if (!c.get('network', route.interface)) die('Интерфейс маршрута не найден');
                let section = c.add('network', 'route');
                set_fields(c, 'network', section, route);
            }
            plan.summary = ['Сохранить статические IPv4-маршруты: ' + length(data.routes)];
            for (let route in data.routes)
                push(plan.summary, route.target + ' / ' + (route.netmask || '255.255.255.255') + ' → ' + (route.gateway || 'напрямую') + ' (' + route.interface + ')');
        } else if (action == 'delete') {
            if (management)
                die('Интерфейс доступа к панели нельзя удалить');
            c.delete('network', name);
            let peers = [];
            c.foreach('network', 'wireguard_' + name, function(s) { push(peers, s['.name']); });
            for (let id in peers) c.delete('network', id);
            let routes = [];
            c.foreach('network', 'route', function(s) { if (s.interface == name) push(routes, s['.name']); });
            for (let id in routes) c.delete('network', id);
            plan.summary = ['Удалить интерфейс ' + name + ' и его настройки WireGuard'];
            if (length(routes)) push(plan.summary, 'Удалить связанные IPv4-маршруты: ' + length(routes));
        } else {
            validate_fields(data.settings, [...interface_fields, 'password', 'private_key']);
            if (!current) c.set('network', name, 'interface');
            if (data.settings.proto && index(['static', 'dhcp', 'pppoe', 'wireguard', 'none'], data.settings.proto) < 0) die('Протокол не поддерживается');
            if (data.settings.proto == 'pppoe' && !access('/lib/netifd/proto/ppp.sh')) die('Для PPPoE сначала установите пакет ppp-mod-pppoe во вкладке «Пакеты»');
            if (data.settings.proto == 'wireguard' && !access('/lib/netifd/proto/wireguard.sh')) die('Для WireGuard сначала установите wireguard-tools во вкладке «Пакеты»');
            set_fields(c, 'network', name, data.settings);
            if (data.peers != null) {
                if ((data.settings.proto || current?.proto) != 'wireguard' || type(data.peers) != 'array' || length(data.peers) > 32) die('Некорректные пиры WireGuard');
                let peers = [];
                c.foreach('network', 'wireguard_' + name, function(s) { push(peers, s); });
                let saved = {};
                for (let peer in peers) { saved[peer['.name']] = peer.preshared_key; c.delete('network', peer['.name']); }
                for (let peer in data.peers) {
                    let id = peer.id;
                    if (id != null && !match(id, /^[a-zA-Z0-9_]+$/)) die('Некорректный пир');
                    let settings = { ...peer }; delete settings.id;
                    validate_fields(settings, [...peer_fields, 'preshared_key']);
                    let section = c.add('network', 'wireguard_' + name);
                    set_fields(c, 'network', section, settings);
                    if (settings.preshared_key == null && saved[id]) c.set('network', section, 'preshared_key', saved[id]);
                }
                push(plan.summary, 'WireGuard: сохранить пиры (' + length(data.peers) + ')');
            }
            for (let key, value in data.settings) {
                if (sprintf('%J', current?.[key] || null) == sprintf('%J', value)) continue;
                push(plan.summary, name + ' / ' + key + ': ' + (index(['password', 'private_key'], key) >= 0 ? 'новое скрытое значение' : value == null ? 'сбросить' : type(value) == 'array' ? join(', ', value) : value));
            }
            if (management && data.settings.ipaddr && index(api_addresses,data.settings.ipaddr) < 0) {
                plan.new_api_host = data.settings.ipaddr;
                put(dir + '/uhttpd.before', readfile('/etc/config/uhttpd'));
                put(dir + '/uci/uhttpd', readfile('/etc/config/uhttpd'));
                let u = cursor(dir + '/uci', dir + '/delta');
                for (let option in ['listen_http', 'listen_https']) {
                    let values = u.get('uhttpd', 'main', option) || [];
                    if (type(values) != 'array') values = [values];
                    let changed = map(values, function(value) {
                        for (let old in api_addresses) if (substr(value,0,length(old)+1)==old+':') return plan.new_api_host + substr(value,length(old));
                        return value;
                    });
                    u.set('uhttpd', 'main', option, changed);
                }
                if (!u.commit('uhttpd')) die('Не удалось подготовить адрес HTTPS');
                put(dir + '/uhttpd.after', readfile(dir + '/uci/uhttpd'));
                plan.uhttpd_before = digest(dir + '/uhttpd.before'); plan.uhttpd_after = digest(dir + '/uhttpd.after');
            }
        }
        if (!c.commit('network')) die('Не удалось подготовить конфигурацию UCI');
        put(dir + '/network.after', readfile(dir + '/uci/network'));
        plan.after_hash = digest(dir + '/network.after');
        expected += ':' + plan.after_hash + ':' + (plan.uhttpd_after || '');
    }
    plan.expected = expected;
    return plan;
}
export { configuration, prepare };
