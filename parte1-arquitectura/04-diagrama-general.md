# 4. Diagrama general de arquitectura

**Convenciones:** las flechas **sólidas** (`──▶`) son comunicación **síncrona** (HTTPS/REST o gRPC). Las flechas **punteadas** (`┄┄▶`) son comunicación **asíncrona** (eventos en Kafka o tareas en RabbitMQ).

```mermaid
flowchart LR
    %% ---------- Zona pública ----------
    subgraph PUB["🌐 Zona pública"]
        WEB["App web / móvil"]
        CDN["CDN + WAF<br/>(anti-bots, caché de cuotas y carreras)"]
        GW["API Gateway<br/>(JWT, rate limiting, TLS)"]
        IDP["IdP administrado<br/>(login, MFA, tokens)"]
    end

    %% ---------- Zona privada ----------
    subgraph PRIV["🔒 Red privada (VPC)"]
        subgraph CORE["Core — monolito modular"]
            MU["Usuarios"]
            MM["Medianos"]
            MC["Carreras + Resultados"]
            MA["Admin"]
        end

        subgraph APU["Servicio Apuestas"]
            AAPI["Apuestas-API<br/>(autoescalado 2→N)"]
            ALIQ["Liquidador<br/>(workers 0→N)"]
        end

        WAL["Billetera / Ledger<br/>(gRPC interno)"]
        NOT["Notificaciones<br/>(worker)"]
        AUD["Auditoría y Fraude"]

        KAFKA[["Kafka<br/>(log de eventos)"]]
        RMQ[["RabbitMQ<br/>(colas de trabajo)"]]

        DBCORE[("PostgreSQL Core<br/>esquemas por módulo")]
        DBAPU[("PostgreSQL Apuestas<br/>particionada por carrera<br/>+ réplica de lectura")]
        DBWAL[("PostgreSQL Billetera<br/>Multi-AZ, PITR")]
        REDIS[("Redis<br/>estado de carreras,<br/>cuotas, bloqueados")]
        LAKE[("Data lake S3 / Parquet<br/>+ motor SQL")]
        WORM[("S3 Object Lock<br/>auditoría 5 años")]
    end

    EXT["Proveedores:<br/>Email / Push"]

    %% ---------- Síncrono ----------
    WEB --> CDN --> GW
    WEB --> IDP
    GW --> CORE
    GW --> AAPI
    GW -->|"saldo / movimientos<br/>(solo lectura)"| WAL
    GW -->|"rol AUDITOR"| AUD
    AAPI -->|"gRPC: Debitar"| WAL
    ALIQ -->|"gRPC: AcreditarLote"| WAL
    AAPI --> REDIS
    AAPI --> DBAPU
    ALIQ --> DBAPU
    CORE --> DBCORE
    WAL --> DBWAL
    NOT --> EXT

    %% ---------- Asíncrono ----------
    CORE -.->|"CarreraAbierta / Cerrada /<br/>ResultadoPublicado / Cancelada"| KAFKA
    AAPI -.->|"ApuestaRealizada<br/>(outbox)"| KAFKA
    WAL -.->|"MovimientoRegistrado<br/>(outbox)"| KAFKA
    ALIQ -.->|"PremioCalculado / PremioPagado"| KAFKA
    KAFKA -.-> APU
    KAFKA -.-> NOT
    KAFKA -.-> AUD
    KAFKA -.->|"Kafka Connect"| LAKE
    AUD -.-> WORM
    ALIQ -.->|"lotes de liquidación"| RMQ
    RMQ -.-> ALIQ
    NOT -.->|"envíos por canal<br/>(email / push / app)"| RMQ
    RMQ -.-> NOT
```

## Lectura del diagrama en 5 pasos

1. **Entrada única.** Todo el tráfico de usuarios pasa por CDN + WAF → API Gateway. El Gateway valida el JWT emitido por el IdP y aplica *rate limiting*. Nada de la VPC es accesible directamente desde Internet.
2. **Camino caliente (apostar).** Gateway → Apuestas‑API. La API lee de Redis el estado de la carrera y los participantes, debita en la Billetera por gRPC y guarda la apuesta junto con su evento en la *outbox* en una sola transacción. Responde en menos de 1 s.
3. **Difusión de hechos.** Cada servicio publica sus eventos en **Kafka**. Notificaciones, Auditoría/Fraude, el data lake y la proyección de cuotas los consumen de forma independiente y a su propio ritmo.
4. **Trabajo pesado.** Al publicarse un resultado, el Liquidador divide la carrera en lotes y los reparte por **RabbitMQ** entre N *workers*, que acreditan premios en la Billetera.
5. **Datos.** Cada servicio es dueño de su base de datos. El histórico de eventos queda en el data lake (analítica) y en almacenamiento inalterable (auditoría).

## Zonas de red (resumen; el detalle va en la Fase 4)

| Pública | Privada |
|---|---|
| CDN, WAF, API Gateway, IdP | Core, Apuestas, Billetera, Notificaciones, Auditoría y Fraude, Kafka, RabbitMQ, PostgreSQL, Redis, data lake |
