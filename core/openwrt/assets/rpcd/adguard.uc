'use strict';
import { readfile, popen, access } from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
function ports() {
    let result = [];
    for (let name in ['tcp', 'tcp6', 'udp', 'udp6']) {
        for (let line in split(readfile('/proc/net/' + name) || '', '\n')) {
            let f = split(trim(line), /\s+/);
            if (length(f) < 4 || !match(f[1], /:[A-Fa-f0-9]{4}$/)) continue;
            if (substr(name, 0, 3) == 'tcp' && f[3] != '0A') continue;
            let p = int('0x' + split(f[1], ':')[1]);
            let protocol = substr(name, 0, 3);
            if (!length(filter(result, x => x.port == p && x.protocol == protocol))) push(result, { port: p, protocol });
        }
    }
    return result;
}
function information() {
    let c = cursor(), root = '/opt/AdGuardHome';
    let init = readfile('/etc/init.d/adguardhome') || '';
    let managed = index(init, '# Bot4VPS managed GitHub installation.') >= 0;
    let yaml = managed ? readfile(root + '/AdGuardHome.yaml') || '' : '';
    let web_port = 3000, dns_port = 5353, block = '', configured = length(yaml) > 0;
    for (let line in split(yaml, '\n')) {
        let top = match(line, /^([a-z_]+):/); if (top) block = top[1];
        let port = match(line, /^\s+port:\s*([0-9]+)/);
        if (block == 'dns' && port) dns_port = int(port[1]);
        let address = match(line, /^\s+address:\s*['"]?[^\n]*:([0-9]+)['"]?\s*$/);
        if (block == 'http' && address) web_port = int(address[1]);
        let old = match(line, /^bind_port:\s*([0-9]+)/); if (old) web_port = int(old[1]);
    }
    let bound = ports();
    let bus = connect(), networks = bus ? bus.call('network.interface', 'dump', {}) : {};
    let addresses = ['127.0.0.1', '::1'];
    for (let iface in networks?.interface || []) for (let ip in iface['ipv4-address'] || []) push(addresses, ip.address);
    let dependencies = [], resolvers = [];
    c.foreach('dhcp', 'dnsmasq', function(s) {
        let port = int(s.port == null ? '53' : s.port);
        push(resolvers, { id: s['.name'], port });
        if (configured && dns_port == 53 && port != 53) push(dependencies, 'dnsmasq не обслуживает порт 53; клиенты могут зависеть от AdGuard Home');
        let servers = s.server || []; if (type(servers) != 'array') servers = [servers];
        for (let server in servers) {
            let tail = split(server, '/'); let target = tail[length(tail) - 1];
            let parts = split(target, '#');
            if (index(addresses, parts[0]) >= 0 && int(parts[1] || '53') == dns_port) push(dependencies, s['.name'] + ': upstream ' + server);
        }
    });
    let space = popen('df -Pk /opt 2>/dev/null');
    let text = space ? space.read('all') : ''; if (space) space.close();
    let rows = split(trim(text), '\n'), columns = split(trim(rows[length(rows) - 1] || ''), /\s+/);
    let free = length(columns) >= 4 ? int(columns[3]) * 1024 : null;
    return { installed: access('/etc/init.d/adguardhome'), managed, configured, root, web_port, dns_port, occupied_ports: bound,
        setup_port_busy: length(filter(bound, x => x.protocol == 'tcp' && x.port == 3000)) > 0,
        free_bytes: free, dns_dependencies: dependencies, dnsmasq: resolvers };
}
export { information, ports };
