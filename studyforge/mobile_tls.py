"""A persistent local CA and short-lived server certificate for LAN access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def certificates(directory: Path, addresses: list[str]) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    root_file, root_key_file = directory / 'studyforge-mobile-ca.cer', directory / 'ca-key.pem'
    stamp = datetime.now(timezone.utc)
    if root_file.exists() and root_key_file.exists():
        root = x509.load_der_x509_certificate(root_file.read_bytes())
        root_key = serialization.load_pem_private_key(root_key_file.read_bytes(), password=None)
        if root.not_valid_after_utc < stamp + timedelta(days=30):
            raise ValueError('手机连接证书即将到期，请移除手机上的旧证书并重置连接证书')
    else:
        root_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'StudyForge Personal Mobile CA')])
        root = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(root_key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(stamp - timedelta(days=1))
                .not_valid_after(stamp + timedelta(days=365 * 3))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                    encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
                .sign(root_key, hashes.SHA256()))
        root_key_file.write_bytes(root_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
        root_key_file.chmod(0o600)
        root_file.write_bytes(root.public_bytes(serialization.Encoding.DER))
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'StudyForge Mobile')]))
            .issuer_name(root.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(stamp - timedelta(days=1)).not_valid_after(stamp + timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))
                for address in sorted(set(addresses + ['127.0.0.1']))] + [x509.DNSName('localhost')]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
            .sign(root_key, hashes.SHA256()))
    cert_file, key_file = directory / 'server-chain.pem', directory / 'server-key.pem'
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_file.chmod(0o600)
    fingerprint = root.fingerprint(hashes.SHA256()).hex().upper()
    return {'certificate': str(cert_file), 'key': str(key_file), 'ca': str(root_file),
            'expires_at': leaf.not_valid_after_utc.isoformat(),
            'fingerprint': ':'.join(fingerprint[i:i + 2] for i in range(0, len(fingerprint), 2))}
