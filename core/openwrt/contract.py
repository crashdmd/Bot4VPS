"""The shared versioned contract shipped to both panel and rpcd."""
from pathlib import Path
import json
import hashlib

CONTRACT = json.loads((Path(__file__).parent/'assets/contract.json').read_text())
VERSION = CONTRACT['version']

from core.openwrt.components import FILES

COMPONENTS = FILES


def hashes():
    root = Path(__file__).parent / 'assets'
    return {target: hashlib.sha256((root/source).read_bytes()).hexdigest() for target, source in COMPONENTS.items()}


async def check(rpc, object_name):
    from core.openwrt.rpc import RpcError
    reply = await rpc.call(object_name,'capabilities')
    if reply.get('protocol_version') != VERSION:
        raise RpcError('Версии интеграции панели и rpcd не совпадают. Синхронизируйте компонент Bot4VPS перед изменениями.', 'contract')
    if reply.get('component_hashes') != hashes():
        raise RpcError('Компоненты rpcd отличаются от версии панели. Обновите интеграцию Bot4VPS перед изменениями.', 'contract')
    return reply
