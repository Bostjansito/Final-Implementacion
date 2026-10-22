# Arquitectura de CrediMarket

## 1. Vista general

```mermaid
flowchart LR
    U["Navegador"] -->|HTTP :8080| FE["Frontend React<br/>(nginx + proxy /api/*)"]

    subgraph Servicios["Microservicios de negocio (FastAPI)"]
        P["Productos :8001"]
        C["Clientes :8002<br/>(emite JWT)"]
        PR["Préstamos API :8003<br/>(modelo ML cargado al iniciar)"]
        PRW["Préstamos worker<br/>consumidor + outbox + temporizador"]
        I["Inventario API :8004"]
        IW["Inventario worker<br/>consumidor + outbox + vencimientos"]
    end

    FE --> P & C & PR & I
    PR -->|"REST + token de servicio<br/>perfil del cliente"| C
    PR -->|"REST + token de servicio<br/>cotización vigente"| P
    I -->|"REST: ¿existe el producto?"| P

    PRW -.->|"ReservaSolicitada / LiberacionSolicitada"| MQ[["RabbitMQ"]]
    MQ -.-> IW
    IW -.->|"InventarioReservado / Insuficiente /<br/>ReservaLiberada / Vencida / SalidaConfirmada"| MQ
    MQ -.-> PRW

    P --> R[("Redis<br/>cache-aside")]
    P --> DBP[("productos_db")]
    C --> DBC[("clientes_db")]
    PR & PRW --> DBPR[("prestamos_db")]
    I & IW --> DBI[("inventario_db")]
    PR -->|lee| REG["ml/registry<br/>active.json + modelos"]
    T["ml-trainer (fuera de línea)"] --> MLF["MLflow :5000"]
    T --> REG
```

* Línea sólida: llamada síncrona HTTP. Línea punteada: mensaje asíncrono por RabbitMQ.
* **Una sola instancia de PostgreSQL** con **cuatro bases lógicas** y **cuatro usuarios** (`productos_user`, …).
  Cada usuario solo puede conectarse a su base (`REVOKE ALL … FROM PUBLIC`): está prohibido y es imposible consultar tablas de otro servicio.
* RabbitMQ, Redis, PostgreSQL y MLflow son infraestructura. El entrenamiento es un proceso fuera de línea (`ml-trainer`, perfil `ml`), no un quinto servicio.
* Cada servicio que usa mensajería tiene dos procesos con la **misma imagen y la misma base**: la API y un *worker*. Siguen siendo un solo microservicio.

## 2. Responsabilidades

| Servicio | Hace | No hace |
|---|---|---|
| **Productos** | CRUD de productos, precio, categoría y **versión** (cada cambio incrementa la versión e historial de precios). Caché Redis *cache-aside*. Cotización interna leída **siempre** de PostgreSQL. | No maneja existencias ni decide préstamos. |
| **Clientes** | Registro, consulta y actualización de clientes con información financiera y laboral. Importación CSV idempotente. Usuarios y emisión de JWT (RS256). | No ejecuta el modelo ni toca inventario. |
| **Préstamos** | `POST /prestamos` con `Idempotency-Key`. Reúne datos por API, ejecuta el pipeline, aplica reglas y gestiona la máquina de estados. Publica comandos (outbox) y consume eventos de Inventario. | No lee tablas de otros servicios. No confía en precios enviados por el cliente. |
| **Inventario** | Existencias, reserva **atómica** (`UPDATE … WHERE disponible >= cantidad` + `CHECK disponible >= 0`), liberación, confirmación de salida, vencimiento de reservas y movimientos. | No conoce información financiera del cliente. |

## 3. Secuencia del flujo de financiación

```mermaid
sequenceDiagram
    autonumber
    actor Cl as Cliente (navegador)
    participant PR as Préstamos API
    participant C as Clientes
    participant P as Productos
    participant DB as prestamos_db
    participant W as Préstamos worker
    participant MQ as RabbitMQ
    participant IW as Inventario worker
    participant IDB as inventario_db

    Cl->>PR: POST /prestamos (JWT, Idempotency-Key, producto, cantidad, plazo)
    PR->>DB: INSERT préstamo EVALUANDO (UNIQUE usuario + clave)
    PR->>C: GET /internal/clientes/{id} (token de servicio)
    PR->>P: GET /internal/productos/{id}/cotizacion (fuente de verdad)
    PR->>PR: características -> pipeline -> probabilidad -> reglas
    alt riesgo alto o regla incumplida
        PR->>DB: RECHAZADA (+ versión del modelo)
        PR-->>Cl: 201 RECHAZADA
    else favorable
        PR->>DB: PENDIENTE_INVENTARIO + outbox ReservaSolicitada (misma transacción)
        PR-->>Cl: 202 Accepted + Location /prestamos/{id}
        W->>MQ: publica outbox (publisher confirms)
        MQ->>IW: ReservaSolicitada
        IW->>IDB: inbox(event_id) + UPDATE atómico + reserva + outbox (una transacción)
        IW->>MQ: InventarioReservado o InventarioInsuficiente
        MQ->>W: evento
        W->>DB: inbox(event_id) + APROBADA o CANCELADA_SIN_STOCK
    end
    loop cada 3 s
        Cl->>PR: GET /prestamos/{id}
    end
```

## 4. Seguridad

| Tema | Implementación |
|---|---|
| Autenticación | JWT **RS256** de 30 min emitido por Clientes. Solo Clientes tiene la clave privada; los demás servicios verifican con la pública. |
| Roles | `CLIENTE` y `ADMIN`, validados **en el backend** de cada servicio. El frontend solo oculta menús. |
| Propiedad | Un cliente solo ve y cancela **sus** préstamos (`usuario_id` del token, nunca del cuerpo) y solo ve y edita **su** ficha de cliente. |
| Llamadas internas | Endpoints `/internal/*` exigen un **token de servicio** HS256 de 60 s firmado con un secreto interno (o rol ADMIN). Un `cliente_id` recibido nunca basta. |
| Secretos | Los genera `secrets-init` en `./.secrets` (ignorado por Git) y se montan en `/run/secrets` (`*_FILE`). El repositorio y el compose no contienen secretos. |
| Contraseñas | `scrypt` con sal (librería estándar). |
| Entradas | Pydantic con `extra="forbid"`: p. ej. un `precio` enviado por el cliente → 422. |
| Frontend | Solo habla con las APIs (proxy nginx, mismo origen). CORS configurable con `CORS_ORIGINS`. Sin secretos en el código. |

## 5. Puertos

| Componente | URL |
|---|---|
| Frontend | http://localhost:8080 |
| Productos / Clientes / Préstamos / Inventario | http://localhost:8001 … 8004 (documentación OpenAPI en `/docs`) |
| MLflow | http://localhost:5000 |
| RabbitMQ (administración) | http://localhost:15672 |
