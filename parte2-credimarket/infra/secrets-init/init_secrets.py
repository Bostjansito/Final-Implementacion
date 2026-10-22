"""Genera los secretos locales la primera vez que se levanta el sistema.

Los archivos se escriben en ./.secrets (ignorado por Git). Si un secreto ya
existe no se regenera, así que reiniciar el sistema conserva credenciales.
"""
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DESTINO = Path(os.environ.get("SECRETS_DIR", "/secrets"))

PASSWORDS = [
    "postgres_password",
    "productos_db_password",
    "clientes_db_password",
    "prestamos_db_password",
    "inventario_db_password",
    "rabbitmq_password",
    "redis_password",
    "internal_service_secret",
    "admin_password",
    "demo_cliente_password",
]


def escribir(nombre: str, contenido: str) -> None:
    ruta = DESTINO / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    print(f"  generado: {nombre}")


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    print(f"Inicializando secretos en {DESTINO}")

    for nombre in PASSWORDS:
        if not (DESTINO / nombre).exists():
            escribir(nombre, secrets.token_urlsafe(24))

    if not (DESTINO / "jwt_private.pem").exists():
        clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        escribir(
            "jwt_private.pem",
            clave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )
        escribir(
            "jwt_public.pem",
            clave.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode(),
        )

    # RabbitMQ lee su usuario por defecto desde conf.d
    rabbit_pass = (DESTINO / "rabbitmq_password").read_text().strip()
    escribir(
        "rabbitmq/10-credimarket.conf",
        f"default_user = credimarket\ndefault_pass = {rabbit_pass}\n",
    )

    admin = (DESTINO / "admin_password").read_text().strip()
    demo = (DESTINO / "demo_cliente_password").read_text().strip()
    escribir(
        "cuentas-demo.txt",
        "Cuentas de prueba (solo entorno local)\n"
        "=======================================\n"
        f"Administrador : admin@credimarket.test / {admin}\n"
        f"Cliente (riesgo bajo) : ana.bajo@credimarket.test / {demo}\n"
        f"Cliente (riesgo alto) : bruno.alto@credimarket.test / {demo}\n"
        f"Cliente (otro)        : carla.otra@credimarket.test / {demo}\n"
        "RabbitMQ UI   : http://localhost:15672  usuario credimarket / "
        f"{rabbit_pass}\n",
    )

    # Permisos de lectura para los contenedores que corren con otro usuario
    for ruta in DESTINO.rglob("*"):
        try:
            os.chmod(ruta, 0o755 if ruta.is_dir() else 0o644)
        except OSError:
            pass
    print("Secretos listos.")


if __name__ == "__main__":
    main()
