# Trabajo de Arquitectura de Software
## La Gran Liga de Apuestas de Medianos EIA

---

## Contexto

**UNIVERSIDAD EIA**  
*SER, SABER SERVIR*

Hace varios años, en una zona misteriosa ubicada detrás de los laboratorios de la Universidad EIA, vivía pacíficamente una pequeña comunidad de medianos.

Los medianos llevaban una vida tranquila: comían siete veces al día, evitaban las clases de las 6:00 a. m. y discutían constantemente sobre cuál cafetería de la Universidad vendía el mejor almuerzo.

Todo cambió cuando apareció Dyllan, el gigante de Salchipapa Maker.

Dyllan, obsesionado con encontrar nuevos participantes para sus experimentos deportivos, capturó a los medianos y creó la primera:

**Liga Profesional de Carreras de Medianos de la Universidad EIA.**

Las carreras rápidamente se volvieron populares. Profesores, estudiantes, administrativos y misteriosos personajes externos comenzaron a apostar créditos ficticios llamados **EIA Coins** sobre cuál mediano ganaría cada carrera.

> **Nota:** los EIA Coins son créditos ficticios de este enunciado: no tienen valor monetario, no se compran ni se canjean. El ejercicio no promueve apuestas con dinero real.

Lo que comenzó como una hoja de cálculo manejada por Dyllan terminó convirtiéndose en un negocio inesperadamente grande. Ahora existen miles de usuarios, cientos de carreras, estadísticas históricas, apuestas en tiempo real y transmisiones en vivo.

Dyllan necesita una plataforma tecnológica profesional. El problema es que Dyllan sabe hacer salchipapas, pero no sabe diseñar sistemas distribuidos. Su equipo deberá hacerlo por él.

---

## El reto

La empresa **Salchipapa Maker Racing S.A.S.** los ha contratado como arquitectos de software. Su misión será diseñar la arquitectura tecnológica de la plataforma de apuestas de carreras de medianos.

**No deberán implementar la solución.** El objetivo del trabajo es analizar el problema y tomar decisiones arquitectónicas justificadas. Deberán decidir, entre otras cosas:

* Si la solución debe construirse como un monolito.
* Si debe utilizar una arquitectura de microservicios.
* Si sería conveniente utilizar una arquitectura híbrida.
* Qué operaciones deberían comunicarse de manera síncrona.
* Qué operaciones deberían funcionar mediante eventos.
* Cuándo utilizar RabbitMQ.
* Cuándo utilizar Kafka.
* Cómo soportar grandes cantidades de información.
* Cómo evitar operaciones duplicadas mediante idempotencia.
* Cómo mantener consistentes los datos entre componentes.
* Cómo mantener la plataforma segura.
* Y cómo evitar que la infraestructura cueste más que todos los medianos juntos.

---

## Funcionamiento del negocio

Cada semana se realizan diferentes carreras.

Una **carrera** tiene:
* Identificador
* Fecha y hora
* Pista
* Distancia
* Medianos participantes
* Estado
* Resultados
* Ganador

Los usuarios pueden consultar las carreras disponibles y realizar apuestas utilizando EIA Coins.

Una **apuesta** contiene:
* Usuario
* Carrera
* Mediano seleccionado
* Cantidad apostada
* Fecha
* Identificador único de la operación

Cuando termina una carrera, el sistema recibe los resultados oficiales y determina cuáles apuestas fueron ganadoras. Posteriormente, se acreditan automáticamente las recompensas a las billeteras virtuales de los usuarios.

---

## Reglas del negocio

Para que todos los equipos diseñen sobre los mismos supuestos, se fijan las siguientes reglas:

* **Modelo de premios (apuesta mutua):** todas las apuestas de una carrera forman una bolsa común. La casa retiene una comisión del 10% y el resto se reparte entre las apuestas ganadoras, en proporción al monto apostado. Por tanto, el premio final solo se conoce cuando se cierran las apuestas.
* **Cuotas estimadas:** mientras la carrera está abierta, la plataforma muestra a los usuarios una cuota aproximada por mediano, que cambia a medida que llegan apuestas.
* **Cierre de apuestas:** las apuestas se cierran exactamente a la hora de inicio de la carrera, según el reloj del servidor. Una apuesta que llegue después del cierre debe rechazarse, aunque el usuario la haya enviado antes.
* **Varias apuestas:** un usuario puede realizar varias apuestas en la misma carrera, incluso sobre medianos distintos.
* **Cancelación:** si una carrera se cancela, se devuelve el 100% de lo apostado a cada usuario.

### Ciclo de vida de una carrera:
`PROGRAMADA` $\rightarrow$ `ABIERTA` $\rightarrow$ `CERRADA EN CURSO` $\rightarrow$ `FINALIZADA` $\rightarrow$ `LIQUIDADA`

*Una carrera puede pasar a `CANCELADA` desde cualquier estado anterior a `FINALIZADA`.*

---

## Capacidades principales del sistema

La empresa ha identificado las siguientes capacidades:

### 1. Usuarios y autenticación
Debe permitir:
* Registrar usuarios
* Iniciar sesión
* Consultar perfiles
* Administrar roles
* Bloquear usuarios
* Validar permisos

Existen diferentes roles: **apostador**, **operador de carrera**, **administrador** y **auditor**.

La información sensible (contraseñas, datos personales y movimientos de la billetera) debe estar protegida.

### 2. Medianos
Debe almacenar la información de cada competidor. Cada mediano tiene:
* Nombre
* Edad
* Peso
* Historial de carreras
* Victorias
* Derrotas
* Velocidad promedio
* Estado actual

*Ejemplos de competidores:* Frodito Turbo, Bilbo Rápido, Samwise Verstappen, Peregrin Hamilton, Merry Alonso.

Los estudiantes deberán decidir si esta capacidad merece tener un servicio independiente o podría formar parte de otro componente.

### 3. Carreras
Administra:
* Creación de carreras
* Programación
* Participantes
* Horarios
* Pistas
* Inicio de carrera
* Finalización
* Resultados oficiales

Cuando una carrera comienza o termina, otros componentes de la plataforma podrían necesitar conocer inmediatamente esta información. El equipo deberá decidir cómo comunicar estos cambios.

### 4. Apuestas
Debe permitir realizar apuestas sobre las carreras disponibles. Antes de aceptar una apuesta debe comprobarse:
* Que el usuario exista.
* Que la carrera esté abierta a apuestas (antes del cierre).
* Que el mediano participe en la carrera.
* Que el usuario tenga suficientes EIA Coins.
* Que la apuesta no esté duplicada.

Durante carreras importantes se esperan miles de apuestas por segundo. Por esta razón, esta funcionalidad será uno de los puntos más críticos de la arquitectura.

### 5. Billetera de EIA Coins
Cada usuario tendrá una billetera virtual. Debe permitir:
* Consultar saldo.
* Descontar EIA Coins al realizar una apuesta.
* Acreditar premios.
* Consultar movimientos.
* Realizar devoluciones cuando una carrera sea cancelada.

*Nunca debe ser posible gastar dos veces los mismos EIA Coins.*

### 6. Resultados y premios
Cuando termina una carrera debe recibirse el resultado oficial. El sistema deberá:
1. Identificar el ganador.
2. Encontrar las apuestas ganadoras.
3. Calcular los premios.
4. Acreditar los EIA Coins.
5. Registrar cada movimiento.
6. Generar información para auditoría.

Una carrera popular podría acumular más de un millón de apuestas. No sería conveniente intentar procesarlas todas mediante una única petición HTTP.

### 7. Notificaciones
Los usuarios pueden recibir mensajes cuando:
* Una apuesta fue aceptada.
* Comenzó una carrera.
* Terminó una carrera.
* Ganaron una apuesta.
* Recibieron EIA Coins.
* Una carrera fue cancelada.

Las notificaciones pueden enviarse mediante correo electrónico, aplicación móvil o notificaciones push. Una falla en el sistema de notificaciones no debería impedir que una apuesta sea registrada.

### 8. Estadísticas y analítica
Dyllan descubrió que puede vender estadísticas premium sobre los medianos. El sistema deberá almacenar información como:
* Número de apuestas.
* Montos apostados.
* Comportamiento de usuarios.
* Carreras realizadas.
* Rendimiento histórico de los medianos.
* Probabilidades.
* Tendencias.
* Eventos generados por la plataforma.

Cada día podrían producirse millones de registros. El sistema de analítica no necesariamente necesita conocer toda la información en tiempo real.

### 9. Auditoría y control de fraude
Toda operación que afecte saldos, apuestas o resultados debe quedar registrada. El sistema deberá permitir:
* Conservar un registro inalterable de apuestas, movimientos de billetera, premios y cambios de resultados.
* Consultar ese registro con el rol auditor, que solo tiene permisos de lectura.
* Detectar comportamientos sospechosos, como muchas cuentas apostando desde el mismo dispositivo o apuestas masivas segundos antes del cierre.
* Reconstruir, para cualquier carrera, cómo se calcularon sus premios.

---

## El problema de las cargas masivas

La popularidad de una carrera puede cambiar drásticamente.

* Una carrera normal podría tener: **500 usuarios conectados**.
* La final de la *Copa Intersemestral Dyllan Salchipapa Maker* podría tener: **100.000 usuarios conectados simultáneamente**.

Durante los últimos segundos antes del cierre de apuestas pueden llegar miles de solicitudes prácticamente al mismo tiempo.

Su arquitectura deberá explicar:
* Qué componentes deberían poder escalar.
* Cuáles no necesitan escalar de la misma manera.
* Cómo absorberían picos de tráfico.
* Cómo evitarían perder operaciones.
* Qué sucedería si un servicio está temporalmente caído.

---

## Supuestos de diseño

Para que las decisiones puedan evaluarse, se fijan los siguientes supuestos. Pueden ajustarlos si lo justifican explícitamente.

| Aspecto | Supuesto |
| :--- | :--- |
| **Usuarios concurrentes** | 500 en una carrera normal; 100.000 en la final de la Copa Intersemestral. |
| **Pico de apuestas** | 10.000 apuestas por segundo durante los 30 segundos previos al cierre. |
| **Respuesta al apostar** | El usuario debe saber en menos de 1 segundo si su apuesta fue aceptada o rechazada. |
| **Pérdida de datos** | Ninguna apuesta aceptada ni ningún movimiento de billetera puede perderse. |
| **Liquidación de premios** | Todos los premios pagados en menos de 15 minutos después del resultado oficial. |
| **Estadísticas** | Pueden tener minutos de retraso; los reportes premium, hasta un día. |
| **Auditoría** | Los registros se conservan al menos 5 años. |

---

## Idempotencia: Dyllan no quiere pagar dos veces

Uno de los principales problemas detectados durante las pruebas fue el siguiente:
1. Un estudiante realiza una apuesta por 500 EIA Coins.
2. La aplicación demora en responder.
3. El estudiante presiona nuevamente: **APOSTAR**, luego nuevamente: **APOSTAR**, y una cuarta vez porque considera que presionar más fuerte hace que Internet funcione mejor.
4. El sistema recibe cuatro solicitudes.

Su diseño deberá garantizar que una misma operación lógica no sea procesada cuatro veces. Deberán explicar cómo utilizarían mecanismos de idempotencia (por ejemplo: identificadores únicos de operación, idempotency keys, almacenamiento de operaciones procesadas, restricciones únicas en bases de datos, identificadores únicos de eventos).

*No es necesario implementar estos mecanismos. Sí es obligatorio explicar dónde y por qué los utilizarían.*

---

## Comunicación entre componentes

Uno de los principales objetivos del ejercicio será decidir cómo deben comunicarse las diferentes partes del sistema.

### Comunicación síncrona
Por ejemplo: **HTTP/REST**, **gRPC**. Puede tener sentido cuando un servicio necesita conocer inmediatamente la respuesta de otro.

### Comunicación asíncrona
Podrán utilizar eventos o mensajes para operaciones que no necesitan completarse dentro de la misma petición. Por ejemplo:
* `ApuestaRealizada`
* `CarreraIniciada`
* `CarreraFinalizada`
* `ResultadoPublicado`
* `PremioCalculado`
* `PremioPagado`
* `CarreraCancelada`

Su equipo deberá decidir cuáles de estos eventos deberían existir.

### RabbitMQ o Kafka
En caso de utilizar comunicación asíncrona deberán analizar cuál tecnología utilizar.

* **RabbitMQ:** Puede considerarse para escenarios donde interesa especialmente distribuir tareas, utilizar colas, procesar trabajos mediante diferentes consumidores, implementar reintentos o gestionar mensajes pendientes.
  * *Ejemplo conceptual:* Carrera termina $\rightarrow$ Cola de cálculo de premios $\rightarrow$ Workers (Procesamiento de apuestas).
* **Kafka:** Puede considerarse cuando existen grandes volúmenes de eventos, múltiples consumidores interesados en la misma información, almacenamiento del historial de eventos, procesamiento de streams, analítica o necesidad de reproducir eventos posteriormente.
  * *Ejemplo conceptual:* `ApuestaRealizada` $\rightarrow$ Kafka $\rightarrow$ Analítica / Fraude / Estadísticas / Auditoría (Cada consumidor lee el mismo evento de forma independiente y a su propio ritmo).

*No existe obligación de utilizar ambos. El equipo deberá decidir: RabbitMQ, Kafka, ambos o ninguno. La decisión deberá estar argumentada técnicamente.*

---

## Seguridad

La plataforma maneja dinero virtual y operaciones que afectan el saldo de los usuarios. Su diseño deberá considerar como mínimo:
* Autenticación y autorización.
* Roles.
* Protección de APIs.
* Cifrado de comunicaciones.
* Manejo seguro de credenciales.
* Protección de operaciones administrativas.
* Limitación de tasa (*rate limiting*) y protección contra bots.
* Registro de todas las acciones administrativas.

También deberán indicar cuáles componentes deberían ser públicos y cuáles deberían permanecer dentro de una red privada.

---

## Costos

Dyllan estableció una regla: *"No quiero pagar una infraestructura de Netflix para una carrera de cinco medianos."*

Por esta razón, la arquitectura debe considerar el costo. No siempre dividir una aplicación en veinte microservicios representa una mejor arquitectura.

El equipo deberá justificar:
* Cuántos servicios necesita realmente.
* Cuáles componentes pueden compartir infraestructura.
* Cuáles componentes deben escalar independientemente.
* Dónde sería razonable utilizar servicios administrados.
* Cómo evitar infraestructura innecesaria.

---

## Decisiones obligatorias

El equipo deberá responder explícitamente las siguientes preguntas.

### Decisión 1: Estilo arquitectónico
¿Construirían la solución utilizando monolito, monolito modular, microservicios o arquitectura híbrida? ¿Por qué? Mencionen al menos dos alternativas que descartaron y la razón por la cual las descartaron.

### Decisión 2: División de servicios
Definan los componentes o servicios principales de su arquitectura (usuarios, medianos, carreras, apuestas, billetera, resultados, premios, notificaciones, estadísticas, auditoría). No necesariamente cada capacidad debe convertirse en un microservicio.

### Decisión 3: Comunicación síncrona
Indiquen cuáles componentes se comunicarían directamente mediante REST o gRPC completando una tabla:

| Servicio origen | Servicio destino | Protocolo | Información solicitada | ¿Por qué debe ser síncrona? |
| :--- | :--- | :--- | :--- | :--- |

*Indiquen también qué ocurre si el servicio destino no responde a tiempo (timeout, reintento o respuesta alternativa).*

### Decisión 4: Comunicación asíncrona
Definan los principales eventos de la plataforma completando la siguiente tabla:

| Evento | Productor | RabbitMQ / Kafka | Consumidor o consumidores | Clave de partición o routing key |
| :--- | :--- | :--- | :--- | :--- |

*Indiquen además qué información mínima contiene cada evento.*

### Decisión 5: RabbitMQ vs. Kafka
Expliquen cuál utilizarían, dónde lo utilizarían, por qué y qué problema resuelve. Si utilizan ambos, deberán justificar por qué mantener dos tecnologías diferentes representa una ventaja suficiente para asumir la complejidad adicional.

### Decisión 6: Idempotencia
Identifiquen al menos tres operaciones donde exista riesgo de duplicación y expliquen cómo evitarían procesarlas múltiples veces.

### Decisión 7: Grandes volúmenes
Expliquen cómo respondería su arquitectura ante picos de 10.000 apuestas por segundo en los 30 segundos previos al cierre. Identifiquen cuellos de botella, escalabilidad, colas/streams, cómo evitar perder información y cómo validar cierres y saldos negativos en paralelo.

### Decisión 8: Fallos
Analicen los siguientes casos:
* **Caso A:** El sistema de notificaciones está caído. ¿Los usuarios deberían poder seguir apostando?
* **Caso B:** El servicio de billetera está caído. ¿Los usuarios deberían poder seguir apostando?
* **Caso C (opcional):** Diez minutos después del resultado oficial, se corrige el ganador. ¿Cómo corregir el resultado sin perder trazabilidad?

### Decisión 9: Datos y consistencia
Expliquen:
* Qué tipo de base de datos usaría cada servicio o módulo y si la comparten o no.
* Qué datos requieren consistencia fuerte y cuáles eventual.
* Cómo mantener coherentes la apuesta registrada y el descuento en la billetera si están separados.
* Dónde almacenar el histórico de eventos y analítica.

---

## Diseño de la arquitectura

El entregable debe contener:
1. **Diagrama general de arquitectura:** mostrando cliente, API Gateway, servicios/módulos, bases de datos, RabbitMQ/Kafka, consumidores. Diferenciar visualmente comunicación síncrona de asíncrona.
2. **Diagrama de secuencia:** del flujo completo de una apuesta desde que se presiona APOSTAR hasta la confirmación y descuento en billetera.
3. **Diseño de mensajería:** 
   * Si usan RabbitMQ: Exchange, Queue, Producer, Consumer, Routing.
   * Si usan Kafka: Producer, Topic, Partitions, Consumer Groups, Consumers.

---

## Entregable

Cada grupo deberá entregar un documento o presentación con:
1. Arquitectura seleccionada y justificación (con alternativas descartadas).
2. Identificación de servicios/módulos y responsabilidades.
3. Diagrama general de arquitectura.
4. Diagrama de secuencia del flujo de una apuesta.
5. Comunicaciones síncronas (Tabla Decisión 3).
6. Eventos y comunicaciones asíncronas (Tabla Decisión 4).
7. Diseño de RabbitMQ y/o Kafka.
8. Estrategia de idempotencia.
9. Datos y consistencia.
10. Manejo de cargas masivas.
11. Estrategia básica de seguridad (componentes públicos vs. privados).
12. Consideraciones de costo.
13. Manejo de fallos.
14. Registros de decisiones arquitectónicas (ADR) para las 3 decisiones más importantes (máx 1 página c/u: contexto, opciones, decisión, consecuencias).
15. Respuesta a la pregunta final.
16. Conclusiones.

---

## Condiciones y evaluación

* **Grupos:** Máximo 3 estudiantes.
* **Fecha de entrega:** Exposición 4 y 5 de noviembre.
* **Extensión:** Presentación de máximo 20 diapositivas.
* **Uso de IA:** Permitido, pero todo lo entregado debe ser defendible por cualquier integrante.
* **Sustentación:** Cada grupo presentará su arquitectura. Se planteará un cambio de requisitos en vivo (ej. permitir apuestas en vivo).

### Criterios de evaluación
| Criterio | Peso |
| :--- | :--- |
| Justificación del estilo arquitectónico y de la división en servicios | 15% |
| Comunicación síncrona, asíncrona y diseño de la mensajería | 20% |
| Idempotencia, datos y consistencia | 20% |
| Escalabilidad y manejo de fallos | 15% |
| Seguridad y costos | 10% |
| Calidad de los diagramas, los ADR y el documento | 10% |
| Sustentación | 10% |

> **Restricción importante:** NO SE DEBE IMPLEMENTAR LA ARQUITECTURA. No se calificará quién tenga más microservicios.

---

## Pregunta final

> Si ustedes fueran los responsables técnicos de Salchipapa Maker Racing S.A.S., **¿qué arquitectura implementarían hoy y cómo permitirían que evolucionara si la plataforma creciera 100 veces?**

La respuesta deberá estar sustentada en decisiones relacionadas con: complejidad, escalabilidad, resiliencia, consistencia, seguridad, costo y mantenibilidad.

---

> **Idea central del trabajo:**  
> Una buena arquitectura no es aquella que utiliza más tecnologías.  
> Una buena arquitectura es aquella que utiliza la complejidad necesaria para resolver el problema sin agregar complejidad innecesaria.  
> Y, sobre todo: **ningún mediano debe recibir dos premios porque alguien presionó cuatro veces el botón.**