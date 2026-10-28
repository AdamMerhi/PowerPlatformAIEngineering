"""One-off: generate an RSA key pair for Snowflake key-pair auth (POC_SVC user).
Writes keys/poc_svc.p8 (private, PKCS8 PEM) and keys/poc_svc.pub (public, PEM).
Both are git-ignored. Prints the public key body to paste into snowflake/00_bootstrap.sql.
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

out_dir = Path(__file__).resolve().parent.parent / "keys"
out_dir.mkdir(exist_ok=True)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

(out_dir / "poc_svc.p8").write_bytes(private_pem)
(out_dir / "poc_svc.pub").write_bytes(public_pem)

pub_lines = public_pem.decode().strip().splitlines()[1:-1]
print("Public key (paste into 00_bootstrap.sql RSA_PUBLIC_KEY = '...'):")
print("".join(pub_lines))
print()
print(f"Private key saved to: {out_dir / 'poc_svc.p8'}")
