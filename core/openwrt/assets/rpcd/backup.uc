'use strict';
import { access, popen } from 'fs';

function quote(value) { return "'" + replace(value, "'", "'\\''") + "'"; }
function fingerprint() {
    let pipe = popen('sha256sum /etc/config/* 2>/dev/null | sort | sha256sum');
    let output = pipe ? pipe.read('all') : ''; if (pipe) pipe.close();
    return split(trim(output), ' ')[0] || '';
}
function prepare(action, data) {
    if (!access('/sbin/sysupgrade') || index(['create', 'restore', 'reboot'], action) < 0)
        die('Штатное резервное копирование OpenWrt недоступно');
    let before_hash = fingerprint();
    let plan = { kind: 'backup', service: 'backup', action, before_hash, expected: before_hash, expires: time() + 900 };
    if (action == 'restore') {
        if (!match(data.sha256 || '', /^[a-f0-9]{64}$/) || int(data.size) <= 0 || int(data.size) > 32 * 1024 * 1024 || int(data.unpacked_size) <= 0 || int(data.unpacked_size) > 128 * 1024 * 1024)
            die('Недопустимый архив восстановления');
        if (type(data.entries) != 'array' || !length(data.entries) || length(data.entries) > 2000)
            die('Недопустимый состав архива');
        for (let entry in data.entries)
            if (type(entry.path) != 'string' || !length(entry.path) || length(entry.path) > 512 || match(entry.path, /[[:cntrl:]\\]/) || match(entry.path, /(^\/|(^|\/)\.\.?(\/|$)|^(proc|sys|dev|run|tmp|overlay)(\/|$))/) || index(['file', 'dir', 'link'], entry.type) < 0)
                die('Недопустимый путь восстановления');
        plan.archive_sha256 = data.sha256; plan.archive_size = int(data.size); plan.entries = data.entries; plan.unpacked_size = int(data.unpacked_size);
        plan.expected += ':' + data.sha256 + ':' + int(data.size);
    }
    return plan;
}
export { prepare, fingerprint };
