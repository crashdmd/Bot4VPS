#!/usr/bin/ucode
'use strict';
import { connect } from 'ubus';
import { cursor } from 'uci';
import { popen, unlink } from 'fs';
let username = ARGV[0];
if (!match(username || '', /^bot4vps_[a-f0-9]+$/)) exit(1);
// Run outside rpcd: calling its session API from its own handler deadlocks.
let bus = connect();
// session.list streams one response per session; collect every response.
let sessions = bus.call('session', 'list', {}, true);
let rows = type(sessions) == 'array' ? sessions : sessions?.ubus_rpc_session ? [sessions] : [];
if (!length(rows))
    for (let sid, session in (sessions || {})) push(rows, session);
for (let session in rows)
    if (session.data?.username == username)
        bus.call('session', 'destroy', { ubus_rpc_session: session.ubus_rpc_session });
if (!cursor().get('rpcd', username, 'bot4vps_id'))
    unlink('/usr/share/rpcd/acl.d/bot4vps-key-' + substr(username, 8) + '.json');
let reload = popen('/etc/init.d/rpcd reload >/dev/null 2>&1');
if (reload) reload.close();
