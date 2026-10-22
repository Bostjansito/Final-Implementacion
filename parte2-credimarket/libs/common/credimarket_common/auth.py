"""Autenticación y autorización compartida.

* Tokens de usuario: JWT RS256 emitidos solo por el servicio Clientes (tiene la
  clave privada). Los demás servicios solo tienen la clave pública: pueden
  verificar, pero no fabricar tokens.
* Tokens de servicio: JWT HS256 de vida corta firmados con un secreto interno,
  para llamadas entre servicios (p. ej. Préstamos -> Clientes).
"""
import time
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import secreto

EMISOR = "credimarket-clientes"
_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    sub: str
    rol: str  # CLIENTE | ADMIN | SERVICIO
    cliente_id: str | None = None
    email: str | None = None

    @property
    def es_admin(self) -> bool:
        return self.rol == "ADMIN"

    @property
    def es_servicio(self) -> bool:
        return self.rol == "SERVICIO"


@lru_cache
def _clave_publica() -> str:
    return secreto("JWT_PUBLIC_KEY")


@lru_cache
def _secreto_interno() -> str:
    return secreto("INTERNAL_SERVICE_SECRET")


def emitir_token_usuario(clave_privada: str, sub: str, rol: str, cliente_id: str | None,
                         email: str, minutos: int) -> tuple[str, int]:
    ahora = int(time.time())
    exp = ahora + minutos * 60
    payload = {"iss": EMISOR, "sub": sub, "rol": rol, "cliente_id": cliente_id,
               "email": email, "iat": ahora, "exp": exp}
    return jwt.encode(payload, clave_privada, algorithm="RS256"), exp


def token_servicio(nombre_servicio: str, segundos: int = 60) -> str:
    ahora = int(time.time())
    payload = {"iss": "credimarket-interno", "sub": nombre_servicio, "rol": "SERVICIO",
               "iat": ahora, "exp": ahora + segundos}
    return jwt.encode(payload, _secreto_interno(), algorithm="HS256")


def _decodificar(token: str) -> Principal:
    try:
        cabecera = jwt.get_unverified_header(token)
        if cabecera.get("alg") == "RS256":
            datos = jwt.decode(token, _clave_publica(), algorithms=["RS256"], issuer=EMISOR)
        elif cabecera.get("alg") == "HS256":
            datos = jwt.decode(token, _secreto_interno(), algorithms=["HS256"], issuer="credimarket-interno")
        else:
            raise jwt.InvalidTokenError("algoritmo no permitido")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "La sesión expiró",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    return Principal(sub=datos["sub"], rol=datos["rol"], cliente_id=datos.get("cliente_id"),
                     email=datos.get("email"))


def principal_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticación requerida",
                            headers={"WWW-Authenticate": "Bearer"})
    return _decodificar(cred.credentials)


def principal_opcional(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal | None:
    return _decodificar(cred.credentials) if cred else None


def requiere_roles(*roles: str):
    def dependencia(p: Principal = Depends(principal_actual)) -> Principal:
        if p.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permisos para esta operación")
        return p
    return dependencia


requiere_admin = requiere_roles("ADMIN")
requiere_servicio_o_admin = requiere_roles("SERVICIO", "ADMIN")
