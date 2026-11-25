"""OpenWrt usign-compatible Ed25519 signatures; private material stays on panel."""
import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption


def create():
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = os.urandom(8)
    text = 'untrusted comment: Bot4VPS public key\n' + base64.b64encode(b'Ed' + key_id + public).decode() + '\n'
    return {'signing_private_key': base64.b64encode(raw).decode(), 'signing_key_id': key_id.hex()}, text


def sign(config, message):
    raw = base64.b64decode(config['signing_private_key'])
    signature = Ed25519PrivateKey.from_private_bytes(raw).sign(message)
    data = b'Ed' + bytes.fromhex(config['signing_key_id']) + signature
    return 'untrusted comment: Bot4VPS installation plan\n' + base64.b64encode(data).decode() + '\n'
