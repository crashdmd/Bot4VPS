"""Upstream projects used for service releases and their user-facing descriptions."""
PROJECTS = {
    '3x-ui': {'name': '3x-ui', 'author': 'MHSanaei', 'repository': 'MHSanaei/3x-ui',
              'description': 'Панель Xray для управления VPN-подключениями, пользователями, лимитами и статистикой.'},
    'podkop': {'name': 'Podkop', 'author': 'itdoginfo', 'repository': 'itdoginfo/podkop',
               'description': 'Выборочная маршрутизация сайтов и приложений через прокси на OpenWrt (sing-box).'},
    'ssclash': {'name': 'SSClash-Go', 'author': 'zerolabnet', 'repository': 'zerolabnet/SSClash-Go',
                'description': 'Панель Mihomo / Clash для управления прокси и правилами маршрутизации на OpenWrt.'},
    'adguardhome': {'name': 'AdGuard Home', 'author': 'AdGuardTeam', 'repository': 'AdguardTeam/AdGuardHome',
                    'description': 'DNS-фильтр для всей сети: блокировка рекламы, трекеров и нежелательных доменов.'},
}


def public_projects():
    return [{'id': name, **project} for name, project in PROJECTS.items()]
