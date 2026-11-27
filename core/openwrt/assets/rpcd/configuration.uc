'use strict';
import { readfile, open, popen, mkdir } from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';

let dhcp_fields = ['ignore', 'start', 'limit', 'leasetime'];
let host_fields = ['name', 'mac', 'ip'];
let dns_fields = ['port', 'server', 'noresolv', 'cachesize', 'domain', 'local', 'rebind_protection', 'domainneeded', 'boguspriv'];
let default_fields = ['input', 'output', 'forward', 'synflood_protect'];
let zone_fields = ['input', 'output', 'forward', 'masq', 'mtu_fix'];
let rule_fields = ['name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'dest_port', 'target', 'enabled'];
let redirect_fields = ['name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'src_dport', 'dest_port', 'enabled', 'reflection'];
function quote(value) { return "'" + replace(value, "'", "'\\''") + "'"; }
function hash(path) {
    let p = popen('sha256sum ' + quote(path) + ' 2>/dev/null');
    let output = p ? p.read('all') : ''; if (p) p.close();
    return split(trim(output), ' ')[0] || '';
}
function put(path, content) {
    let f = open(path, 'w', 0600); if (!f) die('Не удалось сохранить снимок конфигурации');
    f.write(content); f.close();
}
function fingerprint() {
    let p = popen('cat /etc/config/network /etc/config/dhcp /etc/config/firewall /etc/config/uhttpd 2>/dev/null | sha256sum');
    let output = p ? p.read('all') : ''; if (p) p.close();
    return split(trim(output), ' ')[0] || '';
}
function fields(s, names) { let out = {}; for (let n in names) if (s[n] != null) out[n] = s[n]; return out; }
function host_macs(host) {
    let raw = type(host?.mac) == 'array' ? join(' ', host.mac) : host?.mac || '';
    return filter(split(lc(raw), /[[:space:]]+/), value => length(value));
}
function ipv4_host_address(ip) {
    if (type(ip) != 'string' || !match(ip, /^((0|[1-9][0-9]{0,2})\.){3}(0|[1-9][0-9]{0,2})$/)) return false;
    let octets = map(split(ip, '.'), item => int(item));
    return octets[0] != 127 && octets[0] < 224 && ip != '0.0.0.0' && !length(filter(octets, item => item > 255));
}
function has_ipv6_reservation(host) { return !!(host.duid || host.hostid || host.ip6addr); }
function configuration() {
    let c = cursor(), dhcp = [], dhcp_reservations = [], dns = [], zones = [], rules = [], redirects = [], defaults = {};
    c.foreach('dhcp', 'dhcp', function(s) {
        let options = s.dhcp_option || []; if (type(options) != 'array') options = [options];
        let addresses = [];
        for (let o in options) if (match(o, /^6,/)) addresses = [...addresses, ...slice(split(o, ','), 1)];
        push(dhcp, { id: s['.name'], interface: s.interface, ...fields(s, dhcp_fields), dns: addresses });
    });
    c.foreach('dhcp', 'host', function(s) {
        if (ipv4_host_address(s.ip)) push(dhcp_reservations, {
            id: s['.name'], ...fields(s, host_fields), mac: host_macs(s), shared_ipv6: has_ipv6_reservation(s)
        });
    });
    c.foreach('dhcp', 'dnsmasq', function(s) { push(dns, { id: s['.name'], ...fields(s, dns_fields), nftset: !!s.nftset, ipset: !!s.ipset }); });
    c.foreach('firewall', 'defaults', function(s) { defaults = { id: s['.name'], ...fields(s, default_fields) }; });
    c.foreach('firewall', 'zone', function(s) { push(zones, { id: s['.name'], name: s.name, network: s.network, ...fields(s, zone_fields) }); });
    c.foreach('firewall', 'rule', function(s) { push(rules, { id: s['.name'], ...fields(s, rule_fields) }); });
    c.foreach('firewall', 'redirect', function(s) { push(redirects, { id: s['.name'], target: s.target, ...fields(s, redirect_fields) }); });
    return { config_hashes: { network: hash('/etc/config/network'), wireless: hash('/etc/config/wireless'), dhcp: hash('/etc/config/dhcp'), firewall: hash('/etc/config/firewall'), uhttpd: hash('/etc/config/uhttpd') }, settings_hash: fingerprint(), dhcp, dhcp_reservations, dns, firewall: { defaults, zones, rules, redirects } };
}
function set_fields(c, config, section, values, allowed) {
    if (type(values) != 'object') die('Некорректные параметры конфигурации');
    for (let key, value in values) {
        if (index(allowed, key) < 0) die('Параметр не поддерживается: ' + key);
        if (value != null) {
            let items = type(value) == 'array' ? value : [value];
            if (length(items) > 32) die('Слишком много значений');
            for (let item in items) if (type(item) != 'string' || length(item) > 256 || match(item, /[[:cntrl:]]/)) die('Некорректное значение');
        }
        if (value == null || value == '' || (type(value) == 'array' && !length(value))) c.delete(config, section, key);
        else c.set(config, section, key, value);
    }
}
function reservation_description(ip, macs, name) {
    return ip + (length(macs) ? ' · ' + join(', ', macs) : '') + (name ? ' (' + name + ')' : '');
}
function change_reservation(c, data, plan) {
    let mode = data.mode, id = data.section, old, hosts = [];
    if (index(['add', 'edit', 'delete'], mode) < 0) die('Укажите действие для статической аренды');
    c.foreach('dhcp', 'host', function(host) {
        push(hosts, host);
        if (host['.name'] == id) old = host;
    });
    if (mode != 'add' && (!old || !ipv4_host_address(old.ip))) die('Статическая IPv4-аренда не найдена');
    let old_macs = host_macs(old), previous = old ? reservation_description(old.ip, old_macs, old.name) : '';
    plan.warnings = ['DNSMasq перезапустится. Изменение адреса вступит в силу при обновлении аренды.'];
    if (mode == 'delete') {
        let keep_ipv6 = has_ipv6_reservation(old);
        let deleted = keep_ipv6 ? c.delete('dhcp', id, 'ip') : c.delete('dhcp', id);
        if (!deleted) die('Не удалось удалить статическую аренду IPv4');
        push(plan.summary, 'Удалить статическую IPv4-аренду ' + previous);
        if (keep_ipv6) push(plan.summary, 'Параметры IPv6 этой записи сохранятся.');
        return;
    }
    let settings = data.settings, ip = settings?.ip, name = settings?.name;
    if (type(settings?.mac) != 'string' || length(settings.mac) > 256) die('Некорректный MAC-адрес');
    let macs = host_macs(settings);
    let same_macs = join(' ', sort([...old_macs])) == join(' ', sort([...macs]));
    if ((!length(macs) && (mode == 'add' || length(old_macs))) ||
            length(filter(macs, (value, i) => !match(value, /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/) ||
                value == '00:00:00:00:00:00' || !match(substr(value, 1, 1), /^[02468ace]$/) || index(macs, value) != i)))
        die('Укажите MAC-адрес устройства');
    if (!ipv4_host_address(ip)) die('Укажите IPv4-адрес устройства');
    if (name != null && (type(name) != 'string' || !match(name, /^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/)))
        die('Некорректное имя устройства');
    if (old && has_ipv6_reservation(old) && !same_macs)
        die('Этот MAC используется также для IPv6. Его можно изменить в LuCI.');
    for (let host in hosts)
        if (host['.name'] != id && ((!old || old.ip != ip) && host.ip == ip ||
                !same_macs && length(filter(host_macs(host), value => index(macs, value) >= 0))))
            die('Для этого IPv4 или MAC уже есть статическая аренда');
    let bus = connect(), state = bus ? bus.call('network.interface', 'dump', {}) : null;
    if (type(state?.interface) != 'array') die('Не удалось проверить адреса шлюза');
    for (let iface in state.interface)
        if (length(filter(iface['ipv4-address'] || [], address => address.address == ip)))
            die('IPv4-адрес используется самим шлюзом');
    if (!old) id = c.add('dhcp', 'host');
    if (!id) die('Не удалось создать статическую аренду');
    let changes = {};
    if (!old || old.ip != ip) changes.ip = ip;
    if (!same_macs) changes.mac = length(macs) == 1 ? macs[0] : macs;
    if (name != (old?.name || null)) changes.name = name;
    if (!length(keys(changes))) die('Нет изменений статической аренды');
    set_fields(c, 'dhcp', id, changes, host_fields);
    let next = reservation_description(ip, macs, name);
    push(plan.summary, old ? 'Изменить ' + previous + ' → ' + next : 'Закрепить IPv4-адрес ' + next);
}
function firewall_explanations(before, data) {
    let notes = [], policy_names = { input: 'входящие подключения к роутеру', forward: 'пересылка между сетями', output: 'исходящие подключения роутера' };
    for (let key in ['input', 'forward', 'output'])
        if (data.settings?.[key] == 'ACCEPT' && before.defaults[key] != 'ACCEPT')
            push(notes, 'По умолчанию разрешаются ' + policy_names[key] + '. Это затронет трафик без отдельной политики зоны или правила.');
    if (data.settings?.synflood_protect == '0' && before.defaults.synflood_protect != '0')
        push(notes, 'Защита от SYN-flood будет выключена; роутер станет уязвимее к перегрузке входящими TCP-подключениями.');
    let external = ['wan'];
    for (let zone in before.zones) {
        let networks = type(zone.network) == 'array' ? zone.network : [zone.network || ''];
        if (length(filter(networks, name => match(name, /^wan[0-9]*$/)))) push(external, zone.name);
    }
    for (let zone in data.zones || []) {
        let old = filter(before.zones, item => item.id == zone.id)[0];
        if (!old) continue;
        for (let key in ['input', 'forward'])
            if (zone[key] == 'ACCEPT' && old[key] != 'ACCEPT')
                push(notes, 'Зона ' + old.name + ': разрешаются ' + policy_names[key] + '. ' + (index(external, old.name) >= 0 ? 'Доступ из WAN может открыть службы роутера или устройства внутренних сетей внешним подключениям.' : 'Доступные службы будут определяться остальными правилами firewall.'));
    }
    for (let rule in data.rules || []) {
        let old = rule.id ? filter(before.rules, item => item.id == rule.id)[0] : null;
        let current = { ...(old || {}), ...rule };
        if ((current.target || 'ACCEPT') != 'ACCEPT' || current.enabled == '0' || !(current.src == '*' || index(external, current.src) >= 0)) continue;
        let sources = current.src_ip ? type(current.src_ip) == 'array' ? join(', ', current.src_ip) : current.src_ip : 'любые адреса источника';
        push(notes, 'Правило ' + (current.name || current.id || 'без имени') + ': доступ из ' + (current.src == '*' ? 'любой зоны, включая WAN' : current.src) + ' к ' + (current.dest ? 'сети ' + current.dest : 'самому роутеру') + ', порты ' + (current.dest_port || 'все') + ', ' + sources + '. Проверьте ограничения по адресам и защиту доступных сервисов.');
    }
    for (let id in data.deleted_rules || []) {
        let old = filter(before.rules, item => item.id == id)[0];
        if (old && index(['REJECT', 'DROP'], old.target) >= 0 && old.enabled != '0')
            push(notes, 'Удаляется блокирующее правило ' + (old.name || id) + '. Доступ к этому трафику будут определять оставшиеся правила и политики зон.');
    }
    for (let rule in data.redirects || []) {
        let old = rule.id ? filter(before.redirects, item => item.id == rule.id)[0] : null;
        let current = { ...(old || {}), ...rule };
        if (current.enabled == '0') continue;
        let sources = current.src_ip ? type(current.src_ip) == 'array' ? current.src_ip : [current.src_ip] : [];
        let note = 'Перенаправление ' + (current.name || current.id || 'без имени') + ': ' + current.src + ', порт ' + (current.src_dport || 'прежний') + ' → ' + (current.dest_ip || 'роутер') + ':' + (current.dest_port || current.src_dport || 'прежний') + '. Источник: ' + (length(sources) ? join(', ', sources) : 'любой адрес') + '.';
        if (index(external, current.src) >= 0) {
            let restricted = length(sources) && !length(filter(sources, address => match(address, /\/0$/)));
            note += ' Порт будет доступен из интернета. ' + (restricted
                ? 'Доступ ограничен адресом источника: ' + join(', ', sources) + '.'
                : 'Доступ не ограничен адресом источника (любой адрес).');
        }
        push(notes, note);
    }
    return notes;
}
function prepare(dir, action, data) {
    let original = configuration();
    if (data.config_hash != original.settings_hash) die('Конфигурация изменилась. Обновите форму и проверьте изменения заново.');
    let config = action == 'firewall' || action == 'firewall_restart' ? 'firewall' : 'dhcp';
    let plan = { service: 'network', kind: 'network', action, configs: [], reload: config == 'firewall' ? 'firewall' : 'dnsmasq',
        settings_before: original.settings_hash, before_hash: hash('/etc/config/network'), summary: [], expires: time() + 900 };
    mkdir(dir + '/uci', 0700); mkdir(dir + '/delta', 0700);
    put(dir + '/' + config + '.before', readfile('/etc/config/' + config));
    put(dir + '/uci/' + config, readfile('/etc/config/' + config));
    let c = cursor(dir + '/uci', dir + '/delta');
    if (!c.load(config)) die('Не удалось прочитать снимок UCI');
    if (action == 'dhcp') {
        if (cursor().get('network', data.interface) != 'interface') die('Интерфейс DHCP не найден');
        let selected = filter(original.dhcp, s => s.interface == data.interface);
        if (length(selected) > 1) die('Для этого интерфейса несколько DHCP-секций; проверьте их в LuCI');
        let id = selected[0]?.id || c.add('dhcp', 'dhcp');
        c.set('dhcp', id, 'interface', data.interface);
        let settings = { ...data.settings }, addresses = settings.dns; delete settings.dns;
        if (settings.ignore != '1') {
            let live = cursor(), ip = live.get('network', data.interface, 'ipaddr') || '';
            if (type(ip) == 'array') ip = ip[0];
            let parts = split(ip, '/'), octets = split(parts[0], '.');
            if (length(octets) != 4) die('DHCP-серверу нужен статический IPv4-адрес подключения');
            let prefix = length(parts) == 2 ? int(parts[1]) : null;
            if (prefix == null) {
                let masks = split(live.get('network', data.interface, 'netmask') || '255.255.255.0', '.');
                prefix = 0;
                for (let octet in masks) { let value = int(octet); for (let bit = 7; bit >= 0; bit--) if (value & (1 << bit)) prefix++; }
            }
            if (prefix < 1 || prefix > 30) die('Для DHCP выберите подсеть IPv4 с доступными адресами клиентов');
            let count = 1 << (32 - prefix), start = int(settings.start || '100'), limit = int(settings.limit || '150');
            if (start < 1 || limit < 1 || start + limit > count - 1) die('Диапазон DHCP выходит за границы подсети или включает broadcast');
            let address = 0; for (let octet in octets) address = address * 256 + int(octet);
            let host = address % count;
            if (host >= start && host < start + limit) die('Диапазон DHCP включает адрес самого роутера. Выберите другой начальный адрес или количество.');
        }
        set_fields(c, 'dhcp', id, settings, dhcp_fields);
        if (addresses != null) {
            let options = c.get('dhcp', id, 'dhcp_option') || []; if (type(options) != 'array') options = [options];
            options = filter(options, o => !match(o, /^6,/));
            if (length(addresses)) push(options, '6,' + join(',', addresses));
            if (length(options)) c.set('dhcp', id, 'dhcp_option', options); else c.delete('dhcp', id, 'dhcp_option');
        }
        plan.interface = data.interface;
        push(plan.summary, data.interface + ': DHCP-сервер ' + (settings.ignore == '1' ? 'выключен' : 'включён'));
        if (settings.ignore != '1') push(plan.summary, 'Убедитесь, что в этом сегменте нет другого DHCP-сервера. Уже выданные аренды у клиентов не отзываются.');
    } else if (action == 'dhcp_reservation') {
        change_reservation(c, data, plan);
    } else if (action == 'dns') {
        if (c.get('dhcp', data.section) != 'dnsmasq') die('Экземпляр dnsmasq не найден');
        set_fields(c, 'dhcp', data.section, data.settings, dns_fields);
        push(plan.summary, 'Изменить DNS dnsmasq. DHCP-сервер и правила обхода сохраняются.');
        if (data.settings.port == '0') push(plan.summary, 'DNS dnsmasq будет отключён; DHCP продолжит работу. Сначала проверьте другой DNS-сервис.');
        if (data.settings.noresolv == '1' && !length(data.settings.server || [])) push(plan.summary, 'DNS от WAN отключён и upstream не указан. Внешние имена могут перестать разрешаться.');
    } else if (action == 'firewall') {
        if (!original.firewall.defaults.id) die('Не найдены основные настройки firewall');
        plan.warnings = firewall_explanations(original.firewall, data);
        set_fields(c, 'firewall', original.firewall.defaults.id, data.settings, default_fields);
        for (let zone in data.zones || []) {
            if (c.get('firewall', zone.id) != 'zone') die('Зона firewall не найдена');
            let values = { ...zone }; delete values.id;
            set_fields(c, 'firewall', zone.id, values, zone_fields);
            push(plan.summary, 'Изменить политики зоны ' + c.get('firewall', zone.id, 'name'));
        }
        for (let id in data.deleted_rules || []) { if (c.get('firewall', id) != 'rule') die('Правило не найдено'); c.delete('firewall', id); push(plan.summary, 'Удалить правило ' + id); }
        for (let rule in data.rules || []) {
            let id = rule.id;
            if (id && c.get('firewall', id) != 'rule') die('Правило firewall не найдено');
            if (!id) id = c.add('firewall', 'rule');
            let values = { ...rule }; delete values.id;
            set_fields(c, 'firewall', id, values, rule_fields);
            push(plan.summary, 'Сохранить правило ' + (values.name || id));
        }
        for (let id in data.deleted_redirects || []) {
            if (c.get('firewall', id) != 'redirect' || (c.get('firewall', id, 'target') || 'DNAT') != 'DNAT') die('Перенаправление портов не найдено или является специальным правилом NAT');
            c.delete('firewall', id); push(plan.summary, 'Удалить перенаправление ' + id);
        }
        for (let rule in data.redirects || []) {
            let id = rule.id;
            if (id && (c.get('firewall', id) != 'redirect' || (c.get('firewall', id, 'target') || 'DNAT') != 'DNAT')) die('Перенаправление не найдено или является специальным правилом NAT');
            for (let key in ['src', 'dest']) if (rule[key]) {
                let exists = false;
                for (let zone in original.firewall.zones) if (zone.name == rule[key]) exists = true;
                if (!exists) die('Зона перенаправления не найдена');
            }
            if (!id) {
                if (!rule.src || !rule.dest || !rule.src_dport || !rule.dest_ip) die('Укажите зоны, внешний порт и IP назначения');
                id = c.add('firewall', 'redirect'); c.set('firewall', id, 'target', 'DNAT');
            }
            let values = { ...rule }; delete values.id;
            set_fields(c, 'firewall', id, values, redirect_fields);
            push(plan.summary, 'Сохранить перенаправление ' + (values.name || id));
        }
        push(plan.summary, 'Перезапустить firewall. Текущие соединения могут прерваться; роутер сохранит снимок для отката.');
    } else if (action == 'firewall_restart') push(plan.summary, 'Перезапустить firewall с проверкой доступа и восстановлением при обрыве.');
    else die('Действие конфигурации не поддерживается');
    if (action != 'dhcp_reservation')
        for (let key, value in data.settings || {}) push(plan.summary, key + ': ' + (value == null ? 'по умолчанию' : type(value) == 'array' ? join(', ', value) : value));
    if (action != 'firewall_restart' && (!c.save(config) || !c.commit(config))) die('Не удалось подготовить UCI');
    put(dir + '/' + config + '.after', readfile(dir + '/uci/' + config));
    push(plan.configs, { name: config, before: hash(dir + '/' + config + '.before'), after: hash(dir + '/' + config + '.after') });
    plan.expected = plan.settings_before + ':' + plan.configs[0].after + ':' + action;
    return plan;
}
export { configuration, prepare, fingerprint, firewall_explanations };
