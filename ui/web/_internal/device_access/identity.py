"""Internal server TLS identity learned through private Web pairing.

No public CA or external certificate is needed: the mobile client pins the
public key received in its local pairing invitation. Web stays on HTTP.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import os
from pathlib import Path
import ssl
import tempfile
import threading
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core.json_store import locked

IDENTITY_DIR = Path("data/mobile-api")
_LOCK = threading.RLock()


def _write(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".identity-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def server_identity(public_url: str = "") -> dict:
    IDENTITY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    IDENTITY_DIR.chmod(0o700)
    with locked(IDENTITY_DIR / ".identity.lock", _LOCK):
        key_path, cert_path = IDENTITY_DIR / "key.pem", IDENTITY_DIR / "cert.pem"
        if key_path.exists():
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError("Ключ API повреждён. Восстановите сохранённый ключ сервера.")
        else:
            # Losing only the key must not silently replace an existing identity.
            if cert_path.exists():
                raise ValueError("Ключ API отсутствует. Восстановите сохранённый ключ сервера.")
            key = ec.generate_private_key(ec.SECP256R1())
            _write(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        now = datetime.now(timezone.utc)
        host = urlsplit(public_url).hostname or "localhost"
        try:
            san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            san = x509.DNSName(host.encode("idna").decode("ascii"))
        renew = not cert_path.exists()
        if not renew:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            current = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            expected = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            if current != expected:
                raise ValueError("Ключ и сертификат API не соответствуют друг другу.")
            renew = cert.not_valid_after_utc <= now + timedelta(days=30) or san not in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if renew:
            name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Bot4VPS Mobile API")])
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
            _write(cert_path, cert.public_bytes(serialization.Encoding.PEM))
        key_path.chmod(0o600)
        cert_path.chmod(0o600)
        public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        pin = "sha256/" + base64.b64encode(hashlib.sha256(public).digest()).decode("ascii")
        return {"cert_path": str(cert_path.resolve()), "key_path": str(key_path.resolve()), "server_pin": pin}


def configured_identity(config: dict) -> dict:
    cert, key = config.get("cert_path"), config.get("key_path")
    if not cert and not key:
        return server_identity(config.get("public_url", ""))
    if not cert or not key:
        raise ValueError("Мобильный API: укажите оба пути своего сертификата или оставьте оба пустыми")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    certificate = x509.load_pem_x509_certificate(Path(cert).read_bytes())
    public = certificate.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"cert_path": str(cert), "key_path": str(key), "server_pin": "sha256/" + base64.b64encode(hashlib.sha256(public).digest()).decode("ascii")}
