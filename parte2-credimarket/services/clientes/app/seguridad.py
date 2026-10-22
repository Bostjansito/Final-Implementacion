import base64
import hashlib
import hmac
import os

# scrypt de la librería estándar: costo de memoria alto contra ataques de fuerza bruta
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    sal = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(dk).decode()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        _alg, n, r, p, sal, dk = almacenado.split("$")
        calculado = hashlib.scrypt(password.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r),
                                   p=int(p), dklen=32)
        return hmac.compare_digest(calculado, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False
