# 2. Decisión 1 — Estilo arquitectónico

## Decisión

**Arquitectura híbrida: un monolito modular para el núcleo de bajo tráfico + 4 servicios independientes solo donde la carga, la criticidad o el ciclo de vida lo exigen, comunicados por eventos.**

```
┌──────────────────────────── Monolito modular "Core" ───────────────────────────┐
│  Usuarios/Perfiles/Roles │ Medianos │ Carreras │ Resultados oficiales │ Admin   │
└────────────────────────────────────────────────────────────────────────────────┘
   Servicios independientes:  Apuestas (API + Liquidador) │ Billetera (Ledger)
                              Notificaciones │ Auditoría y Fraude
   Infraestructura administrada: API Gateway + WAF + CDN │ IdP │ Kafka │ RabbitMQ
                                 PostgreSQL │ Redis │ Data lake (S3) + motor SQL
```

## ¿Por qué híbrida?

| Criterio | Cómo lo resuelve el diseño híbrido |
|---|---|
| **Escalabilidad** | Solo Apuestas, Billetera y el Liquidador reciben el pico; escalan solos. El Core tiene tráfico bajo y casi todo cacheable: con 2 réplicas basta. |
| **Resiliencia** | Si fallan Notificaciones, Auditoría o la analítica, se sigue apostando (consumen eventos de forma asíncrona y se ponen al día después). |
| **Consistencia** | La Billetera es un único dueño del saldo, con transacciones ACID. Dentro del Core, los módulos comparten transacciones locales sin sagas. |
| **Seguridad** | La Billetera queda aislada en red privada, con credenciales propias y una superficie de API mínima (solo gRPC interno). |
| **Costo** | 5 desplegables propios en lugar de 10 o más. Liquidador y Notificaciones escalan a cero entre carreras. |
| **Mantenibilidad** | Los módulos del Core tienen fronteras explícitas (paquetes, esquemas de BD separados), así que extraerlos más adelante es barato si crecen. |

### Criterios con los que decidimos qué se separa del Core

Una capacidad se convierte en servicio independiente **solo si cumple al menos uno**:

1. **Perfil de carga distinto:** necesita escalar 10–100× más que el resto (Apuestas, Billetera).
2. **Criticidad o aislamiento de seguridad:** un fallo o una brecha allí es catastrófica (Billetera).
3. **Trabajo por lotes o asíncrono** que no debe competir por recursos con las peticiones de usuario (Liquidador, Notificaciones, Auditoría/Fraude).

Medianos, Usuarios, Carreras y Resultados no cumplen ninguno, así que se quedan en el Core.

## Alternativas descartadas

### ❌ Monolito tradicional (todo en un desplegable)
- **Ventaja:** es lo más simple de operar y de desarrollar al inicio.
- **Por qué se descarta:**
  - En la final de la Copa habría que escalar **toda** la aplicación (medianos, admin, perfiles) solo para absorber las apuestas. Se desperdician recursos.
  - Un trabajo pesado (liquidar 1 M de apuestas) competiría por CPU y conexiones de BD con los usuarios que apuestan en otra carrera.
  - Un fallo en un componente secundario (por ejemplo, el envío de correos) podría tumbar el proceso que acepta apuestas.

### ❌ Microservicios "puros" (un servicio por capacidad, unos 10)
- **Ventaja:** máxima independencia de despliegue y escalado.
- **Por qué se descarta:**
  - Medianos, Usuarios y Carreras tienen poco tráfico: separarlos multiplica bases de datos, pipelines, monitoreo y costo sin beneficio ("infraestructura de Netflix").
  - Más llamadas de red en cadena aumentan la latencia y los puntos de fallo (Apuestas → Usuarios → Carreras → Medianos → Billetera).
  - Se necesitarían sagas y consistencia eventual entre módulos que hoy pueden compartir una transacción local.
  - El equipo es pequeño y la operación de 10 servicios supera su capacidad.

### ❌ Monolito modular sin servicios separados
- Es la alternativa más cercana y fue la segunda opción. Se descarta porque **la Billetera y las Apuestas tienen un perfil de carga y de criticidad radicalmente distinto** al del resto. Además, la liquidación masiva y el *fan-out* de eventos piden procesos independientes. Aun así, el Core **sí** sigue este estilo.

## Riesgos aceptados

| Riesgo | Mitigación |
|---|---|
| El Core podría convertirse en un "monolito enredado". | Un módulo = un paquete + un esquema de BD. Prohibido acceder a tablas de otro módulo; se usan interfaces internas. Las reglas se verifican con pruebas de arquitectura (p. ej., ArchUnit). |
| Separar Apuestas de Billetera exige coordinar dos escrituras. | Débito idempotente + estados de la apuesta + reconciliación (se detalla en la Fase 3, Datos y consistencia). |
| Operar Kafka y RabbitMQ a la vez. | Ambos en modo administrado (Amazon MSK Serverless / Amazon MQ). La justificación completa va en la Decisión 5. |
