# 8. Diagrama de secuencia — flujo completo de una apuesta

Desde que el usuario presiona **APOSTAR** hasta la confirmación y el descuento en la billetera, incluyendo los caminos de duplicado, cierre y saldo insuficiente.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant APP as App web/móvil
    participant GW as CDN + WAF + API Gateway
    participant AP as Apuestas-API
    participant R as Redis
    participant ADB as BD Apuestas
    participant W as Billetera (gRPC)
    participant WDB as BD Billetera
    participant K as Kafka (vía Debezium)
    participant C as Consumidores (cuotas, notif, fraude, auditoría, lake)

    U->>APP: Presiona APOSTAR (carrera C, mediano M, 500 coins)
    APP->>APP: Genera Idempotency-Key K (UUID), una sola vez por intención
    APP->>APP: Deshabilita el botón
    APP->>GW: POST /apuestas (JWT, Idempotency-Key K)
    GW->>GW: TLS, WAF/bots, valida JWT, rate limit por usuario/IP/dispositivo
    GW->>AP: POST /apuestas (usuario_id tomado del JWT)
    AP->>AP: recibida_at = reloj del servidor (NTP)

    AP->>ADB: INSERT apuesta PENDIENTE (UNIQUE usuario_id, K)
    alt K ya existía (reintento o doble clic)
        ADB-->>AP: conflicto de clave única
        AP->>ADB: SELECT apuesta por (usuario_id, K)
        alt mismo contenido
            AP-->>APP: Misma respuesta original (200 o 202 si sigue PENDIENTE)
        else contenido distinto con la misma K
            AP-->>APP: 409 Conflict
        end
    else K nueva
        AP->>R: GET carrera C (estado, cierre_at, participantes) y usuario bloqueado
        R-->>AP: ABIERTA, cierre_at, [M, ...], no bloqueado
        alt recibida_at mayor o igual a cierre_at, o carrera no ABIERTA, o M no participa, o bloqueado
            AP->>ADB: UPDATE apuesta RECHAZADA + outbox ApuestaRechazada
            AP-->>APP: 422 Rechazada (motivo)
        else validaciones OK
            AP->>W: Debitar(op_key = K, usuario, 500, ref = apuesta_id), deadline 300 ms
            W->>WDB: BEGIN
            W->>WDB: INSERT operacion (op_key UNIQUE)
            W->>WDB: UPDATE cuenta SET saldo = saldo - 500 WHERE saldo >= 500
            alt saldo insuficiente (0 filas)
                W->>WDB: ROLLBACK
                W-->>AP: SALDO_INSUFICIENTE
                AP->>ADB: UPDATE apuesta RECHAZADA + outbox ApuestaRechazada
                AP-->>APP: 422 Saldo insuficiente
            else saldo suficiente
                W->>WDB: INSERT movimiento DEBITO_APUESTA + outbox MovimientoRegistrado
                W->>WDB: COMMIT
                W-->>AP: OK (movimiento_id, saldo_resultante)
                AP->>ADB: BEGIN, UPDATE apuesta ACEPTADA + INSERT outbox ApuestaRealizada, COMMIT
                AP-->>GW: 201 Created (apuesta_id, saldo_resultante)
                GW-->>APP: 201 Created
                APP-->>U: Apuesta aceptada. Nuevo saldo 
            end
        end
    end

    Note over AP,WDB: Si Billetera no responde, la apuesta queda PENDIENTE. El cliente reintenta con la misma K o el reconciliador la resuelve consultando ConsultarOperacion(K).

    ADB--)K: Debezium lee el outbox (WAL) y publica ApuestaRealizada
    WDB--)K: Debezium publica MovimientoRegistrado
    K--)C: Cada grupo consume a su ritmo (cuotas en Redis, push "apuesta aceptada", fraude, WORM, data lake)
```

## Presupuesto de latencia (objetivo: p99 < 1 s)

| Paso | Latencia típica |
|---|---|
| CDN/WAF + Gateway (TLS, JWT, *rate limit*) | 20–40 ms |
| INSERT `PENDIENTE` en BD Apuestas | 2–5 ms |
| Lecturas en Redis | < 1 ms |
| gRPC a Billetera + transacción de débito | 5–20 ms |
| UPDATE `ACEPTADA` + outbox | 2–5 ms |
| Red cliente ↔ nube | 50–150 ms |
| **Total** | **~100–250 ms** (holgura de 4× frente al objetivo de 1 s, para absorber el pico) |

## Por qué este orden de pasos

1. **Primero se inserta `PENDIENTE`** con clave única `(usuario_id, idempotency_key)`. Esa fila es la **deduplicación durable**: aunque lleguen 4 clics en paralelo, solo uno gana el INSERT y los demás reciben la respuesta original.
2. **Después se valida y se debita.** El débito usa la misma clave, así que reintentarlo es seguro.
3. **Por último se confirma `ACEPTADA` + outbox** en una sola transacción local: o quedan ambos o ninguno.
4. Si algo falla entre el paso 2 y el 3, la apuesta queda `PENDIENTE` y se resuelve sola (detalle en [10-datos-y-consistencia.md](10-datos-y-consistencia.md)).
