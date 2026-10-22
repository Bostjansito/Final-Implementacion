# CrediMarket: microservicios, mensajería, Redis y MLOps

**Universidad EIA · Trabajo de implementación en grupo**

| Aspecto | Detalle |
| --- | --- |
| **Modalidad** | Grupos de máximo 4 estudiantes. |
| **Qué se construye** | Cuatro microservicios de negocio (Productos, Clientes, Préstamos e Inventario), un frontend web, un modelo de ML con su ciclo MLOps, un broker de mensajería (Kafka o RabbitMQ) y una caché Redis. |
| **Qué se entrega** | Repositorio Git con código, documentación y docker-compose, más una demostración en vivo (ver secciones 13 y 14). |
| **Cómo se evalúa** | Rúbrica de la sección 15 (100 %), aplicada sobre el repositorio y la sustentación. |
| **Fecha de entrega** | Día final de la materia |
| **Datos** | `prestamos_entrenamiento.csv` (12.000 registros) y `solicitudes_nuevas.csv` (200 registros), ambos sintéticos. |

---

## Contenido del enunciado

1. [El reto](#1-el-reto)
2. [Organización del grupo](#2-organización-del-grupo)
3. [Arquitectura y responsabilidades](#3-arquitectura-y-responsabilidades)
4. [Flujo obligatorio de financiación](#4-flujo-obligatorio-de-financiación)
5. [Kafka o RabbitMQ: elegir, implementar y defender](#5-kafka-o-rabbitmq-elegir-implementar-y-defender)
6. [Redis obligatorio: caché real del catálogo](#6-redis-obligatorio-caché-real-del-catálogo)
7. [Datos y objetivo de ML](#7-datos-y-objetivo-de-ml)
8. [Ciclo MLOps obligatorio](#8-ciclo-mlops-obligatorio)
9. [Seguridad, idempotencia e importación masiva](#9-seguridad-idempotencia-e-importación-masiva)
10. [Frontend obligatorio para probar la aplicación](#10-frontend-obligatorio-para-probar-la-aplicación)
11. [Requisitos obligatorios y opcionales](#11-requisitos-obligatorios-y-opcionales)
12. [Pruebas de aceptación](#12-pruebas-de-aceptación)
13. [Entregables](#13-entregables)
14. [Sustentación](#14-sustentación)
15. [Rúbrica de evaluación](#15-rúbrica-de-evaluación)
16. [Documentación oficial de apoyo](#16-documentación-oficial-de-apoyo)

---

## 1. El reto

CrediMarket vende computadores, celulares y otros productos tecnológicos a crédito. Hoy el catálogo, los clientes, los préstamos y el inventario viven en una sola aplicación que falla en el peor momento: cuando dos clientes quieren comprar el último computador, ambos reciben la aprobación. El gerente propone resolverlo comprando otro servidor; ustedes deben proponer e implementar una solución más convincente.

El grupo debe diseñar e implementar:

* **Cuatro microservicios de negocio:** Productos, Clientes, Préstamos e Inventario.
* **Un frontend web (obligatorio)** que permita probar el flujo completo de la aplicación con datos reales.
* **Un modelo de ML** que estime el riesgo de incumplimiento de cada solicitud, con trazabilidad completa de su ciclo de vida en MLflow.
* **Mensajería asíncrona con Kafka o RabbitMQ** para coordinar las reservas de inventario.
* **Una caché Redis verificable** en el servicio de Productos.

> **Importante:** los datos y las operaciones de crédito son ficticios. Se evalúa ingeniería de software y MLOps; no se busca construir una política de crédito aplicable a personas reales.

---

## 2. Organización del grupo

* Cada grupo está conformado por **máximo 4 estudiantes**. Los grupos se registran ante el profesor antes de iniciar el desarrollo.
* El trabajo se desarrolla en un **único repositorio Git compartido**. El historial de commits debe evidenciar contribuciones de los cuatro integrantes.
* Se sugiere distribuir responsabilidades por frente de trabajo (por ejemplo: servicios de Productos e Inventario + Redis; Clientes + seguridad + frontend; Préstamos + broker; datos + modelo + MLOps). La distribución es libre, pero todos los integrantes deben poder explicar cualquier parte del sistema durante la sustentación.
* Incluyan en el `README` una tabla con el nombre de cada integrante y sus responsabilidades principales.
* La nota es grupal; el profesor puede ajustar la nota individual si en la sustentación un integrante no demuestra conocimiento del trabajo entregado (ver sección 14).

---

## 3. Arquitectura y responsabilidades

| Servicio | Responsabilidades obligatorias | Restricciones |
| --- | --- | --- |
| **Productos** | Crear, consultar, actualizar y desactivar productos. Gestionar precio, categoría y versión del producto. Integrar Redis como caché. | No administra existencias ni decide préstamos. |
| **Clientes** | Registrar, consultar y actualizar clientes. Gestionar información financiera y laboral. Permitir importación masiva por CSV. | No ejecuta el modelo ni modifica inventario. |
| **Préstamos** | Recibir solicitudes, reunir datos, ejecutar el modelo, aplicar reglas de negocio, gestionar estados y coordinar reservas y cancelaciones. | Implementado en Python con FastAPI o Flask. El modelo de ML pertenece a este servicio. |
| **Inventario** | Gestionar existencias, reservar unidades, confirmar su salida, liberar reservas y registrar movimientos. | La reserva debe ser atómica; nunca puede generar existencias negativas. |

### Reglas de arquitectura

* **Datos propios:** cada servicio es dueño de sus datos y tiene su propia base de datos lógica o esquema, con credenciales restringidas. Se permite una única instancia de base de datos para reducir consumo, pero está prohibido consultar directamente las tablas de otro servicio; la comunicación es solo por API o mensajes.
* **Infraestructura no cuenta como servicio:** Kafka/RabbitMQ, Redis, la base de datos y MLflow son infraestructura, no microservicios de negocio adicionales.
* **Sin quinto servicio:** el entrenamiento es un proceso fuera de línea; no se crea un servicio aparte para servir el modelo. El frontend tampoco cuenta como microservicio de negocio.
* **Frontend integrado:** debe consumir las APIs implementadas y demostrar las operaciones con datos persistidos.

---

## 4. Flujo obligatorio de financiación

El siguiente flujo es el corazón del sistema y debe funcionar de extremo a extremo:

1. **Solicitud.** Un cliente autenticado solicita un producto, una cantidad y un plazo mediante `POST /prestamos`, incluyendo el encabezado `Idempotency-Key`.
2. **Recolección de datos.** Préstamos obtiene por API la información del cliente (servicio Clientes) y la cotización vigente (servicio Productos). El monto nunca lo decide el cliente ni se confía en un precio enviado por él. Se guarda el precio y la versión de la cotización utilizada.
3. **Evaluación de riesgo.** Préstamos construye las mismas características usadas en el entrenamiento, ejecuta el pipeline exportado y obtiene la probabilidad de incumplimiento.
4. **Reglas de negocio.** Se verifican cliente activo, monto y plazo válidos, información mínima disponible y umbral de riesgo. Si la decisión es desfavorable, el estado pasa a `RECHAZADA` y no se solicita inventario.
5. **Solicitud de reserva.** Si la decisión es favorable, el estado pasa a `PENDIENTE_INVENTARIO`, Préstamos publica el comando `ReservaSolicitada` y responde `HTTP 202` con un identificador consultable.
6. **Reserva.** Inventario procesa el comando y publica `InventarioReservado` o `InventarioInsuficiente`.
7. **Resultado.** Préstamos pasa a `APROBADA` solo después de confirmar la reserva. Si no hay unidades, pasa a `CANCELADA_SIN_STOCK`.
8. **Entrega o cancelación.** La entrega se simula mediante una operación autorizada: Inventario confirma la salida y Préstamos registra `COMPLETADA` al recibir la confirmación. Una cancelación previa a la entrega debe liberar la reserva antes de finalizar como `CANCELADA`.

### Estados mínimos del préstamo

| Estado | Cuándo ocurre | Siguiente estado posible |
| --- | --- | --- |
| **RECHAZADA** | El modelo o las reglas de negocio dan una decisión desfavorable. | Ninguno (final). |
| **PENDIENTE_INVENTARIO** | Riesgo favorable; se publicó `ReservaSolicitada`. | `APROBADA`, `CANCELADA_SIN_STOCK`, `CANCELADA` |
| **APROBADA** | Inventario confirmó la reserva. | `COMPLETADA`, `CANCELADA` |
| **CANCELADA_SIN_STOCK** | Inventario respondió `InventarioInsuficiente`. | Ninguno (final). |
| **COMPLETADA** | Inventario confirmó la salida (entrega simulada). | Ninguno (final). |
| **CANCELADA** | Cancelación antes de la entrega, con reserva liberada. | Ninguno (final). |

**El grupo debe documentar:**
* La máquina de estados completa (diagrama) y los tiempos de espera definidos.
* Qué ocurre si llega una confirmación de reserva después de una cancelación. Un evento tardío nunca puede reactivar una solicitud cancelada.
* Qué ocurre si una reserva vence: debe emitirse un evento y producirse un cambio de estado coherente (el equipo define el nombre del estado o motivo). Un préstamo aprobado no puede conservar una reserva inexistente.

---

## 5. Kafka o RabbitMQ: elegir, implementar y defender

Cada grupo implementa uno de los dos brokers. No basta con instalar el contenedor, hacer un ejemplo aislado o dibujarlo en el diagrama: el broker debe transportar los comandos y eventos reales del flujo entre Préstamos e Inventario.

### 5.1 Decisión de arquitectura (1 a 2 páginas)

Comparen ambas opciones y respondan:
1. ¿Qué volumen, número de consumidores y patrón de comunicación asumen para CrediMarket?
2. ¿Necesitan conservar y reproducir eventos? ¿Durante cuánto tiempo?
3. ¿Cómo funcionan la distribución del trabajo y el orden de procesamiento en su configuración?
4. ¿Cómo manejan errores, mensajes duplicados, reintentos y mensajes que no pueden procesarse?
5. ¿Qué costo de recursos y complejidad operativa tiene cada alternativa?
6. ¿Por qué eligieron una? ¿Qué cambio de requisitos les haría escoger la otra?

### 5.2 Configuración que deben documentar

| Si eligen Kafka | Si eligen RabbitMQ |
| --- | --- |
| Topics, claves de partición, grupos de consumidores, retención y confirmación de offsets. | Exchanges, colas, routing keys, persistencia, confirmaciones de publicación (*publisher confirms*) y acknowledgements. |

> **En ambos casos:** reintentos limitados y un destino para mensajes fallidos (*dead letter*).

### 5.3 Contrato de los mensajes

Cada mensaje debe incluir como mínimo: `event_id` (o `message_id`), `type`, `schema_version`, `occurred_at`, `correlation_id`, `prestamo_id` y `payload`. Incluyan los contratos y ejemplos JSON en el repositorio. No transporten información financiera del cliente si Inventario no la necesita.

> **Ojo:** las garantías del broker no convierten automáticamente las operaciones en base de datos en "exactamente una vez". Los efectos de negocio deben ser idempotentes.

---

## 6. Redis obligatorio: caché real del catálogo

Implementen Redis en el servicio de Productos con el patrón **cache-aside**:
1. Al consultar un producto, intentar obtenerlo primero desde Redis.
2. Si no está (*cache miss*), leer la base de datos y guardar el resultado con TTL.
3. Al actualizar o desactivar un producto, invalidar o actualizar la entrada después de confirmar la escritura en la base de datos.
4. Si Redis falla, seguir respondiendo desde la base de datos con un tiempo de espera acotado.

**Diseño que deben documentar:** claves (por ejemplo `productos:v1:{producto_id}`), TTL, estrategia de invalidación y condiciones en que un dato puede estar desactualizado.

**Precio del préstamo:** la cotización que define el monto debe leerse de la fuente de verdad o validarse por versión. No usen ciegamente un precio antiguo de la caché.

**Evidencia exigida:**
* Demostración de *cache miss*, *cache hit*, expiración, invalidación tras cambiar un precio y recuperación ante caída de Redis.

> **Límites de Redis:** no reemplaza las bases de datos de Préstamos ni de Inventario. La deduplicación de solicitudes y eventos debe ser durable y sobrevivir a la caída o borrado de Redis. Como extensión opcional pueden implementar *rate limiting*, pero no sustituye la caché exigida.

---

## 7. Datos y objetivo de ML

| Archivo | Contenido | Uso |
| --- | --- | --- |
| `prestamos_entrenamiento.csv` | 12.000 registros sintéticos, 15 columnas. Objetivo: `incumplimiento_90d` ($1$ = incumplió en los 90 días siguientes al inicio del préstamo; $0$ = no incumplió). | Entrenamiento, validación y prueba. |
| `solicitudes_nuevas.csv` | 200 solicitudes, 14 columnas, sin variable objetivo. | Solo inferencia. No permite calcular métricas de clasificación. |

### Reglas sobre los datos:
* Los registros son préstamos simulados con resultado conocido, no solicitudes rechazadas. El modelo estima riesgo; una política documentada toma la decisión. No entrenen para predecir una columna de aprobación.
* El diccionario de datos explica unidades, categorías y valores faltantes.
* Los identificadores sirven para trazabilidad; no son variables predictoras.
* El porcentaje de pago puntual describe créditos anteriores y puede estar vacío si no hay historial.
* La tasa mensual es un parámetro ficticio constante. Justifiquen la exclusión de variables constantes o redundantes.
* Nunca usen la etiqueta como entrada del modelo.

---

## 8. Ciclo MLOps obligatorio

El ciclo tiene seis etapas (A a F). Todas son obligatorias.

### A. Validar y versionar los datos
* Revisen tipos, rangos, faltantes, duplicados y distribución de clases. Presenten un análisis exploratorio breve.
* Identifiquen la versión del dataset y su hash SHA-256. Conserven el código de preparación y los identificadores de cada partición.
* Dividan el histórico en entrenamiento, validación y prueba (por ejemplo 60/20/20) con estratificación y semilla fija. En estos archivos cada cliente aparece una sola vez; si amplían los datos con varios registros por cliente, eviten que un mismo cliente quede en particiones distintas.
* Ajusten imputadores, codificadores y escaladores solo con entrenamiento. Toda transformación aprendida forma parte del pipeline.
* **Validación** $\rightarrow$ selección de modelo y umbral. **Prueba** $\rightarrow$ evaluación final únicamente. Si cambian el modelo después de ver la prueba, deben reconocer que ya no es una evaluación independiente.

### B. Entrenar y comparar
* Un baseline trivial y al menos tres algoritmos (por ejemplo: regresión logística, árbol de decisión y random forest). Puede usar PyCaret.
* Al menos seis ejecuciones candidatas además del baseline, variando hiperparámetros de forma justificada.
* **Métricas:** precision, recall y F1 de la clase 1; ROC-AUC; average precision (AP); matriz de confusión. No seleccionen solo por accuracy. Si interpretan la salida como probabilidad, evalúen calibración (Brier score o curva de calibración), sin afirmar que representa riesgo real de personas.
* Definan antes de comparar la métrica de selección y el criterio de desempate. Seleccionen con validación o validación cruzada dentro del conjunto de desarrollo.
* El umbral se ajusta después sobre validación y se congela antes de evaluar en prueba. Para justificarlo, distingan entre aprobar a quien incumplirá y rechazar a quien habría pagado; pueden asignar costos ficticios y mostrar la curva de costo (los costos deben ser explícitos y no son recomendaciones financieras).

### C. Registrar experimentos en MLflow
Usen MLflow Tracking con metadatos y artefactos en almacenamiento persistente. Cada ejecución registra:

| Categoría | Qué registrar |
| --- | --- |
| **Modelo** | Nombre del algoritmo e hiperparámetros; semilla y estrategia de partición. |
| **Datos y código** | Versión/hash de datos, lista de características y versión o commit del código. |
| **Entorno** | Parámetros de preprocesamiento, dependencias del entorno y duración. |
| **Métricas** | Entrenamiento/validación; para el modelo seleccionado, también prueba (con nombres diferenciados). |
| **Artefactos** | Pipeline del modelo, matriz de confusión y reporte de evaluación. |

> La comparación se presenta en la interfaz de MLflow; una captura aislada no reemplaza el historial consultable. No es necesario subir el CSV en cada ejecución si su versión y hash lo identifican.

### D. Seleccionar, exportar y promover
* Expliquen por qué eligieron el modelo y el umbral.
* Exporten el pipeline completo (preprocesamiento + estimador), por ejemplo con `joblib` o como artefacto MLflow.
* Cada versión lleva un manifiesto con: `model_version`, `run_id`, versión/hash del dataset, variables de entrada, clase positiva, umbral, métricas, dependencias y hash del artefacto. Guarden un ejemplo de entrada y salida.
* Implementen una promoción explícita de candidato a versión activa (archivo de configuración, manifiesto o alias del registro de modelos). La API carga una versión identificable y estable; no cambia porque apareció una nueva ejecución ni usa "el último archivo exportado".

### E. Servir con FastAPI o Flask
Préstamos carga el pipeline al iniciar (no se entrena por petición) y expone al menos:

| Endpoint | Comportamiento |
| --- | --- |
| `POST /prestamos` | Inicia el proceso de negocio con cliente, producto, cantidad y plazo. |
| `GET /prestamos/{id}` | Consulta el estado y la decisión de una solicitud autorizada. |
| `POST /riesgo/predict` | Endpoint interno o protegido para probar el pipeline con características válidas; no reserva inventario. |
| `GET /modelo/info` | Informa versión, run ID, variables y umbral activos. |
| `GET /health` | Informa si el proceso responde. |
| `GET /ready` | Informa si el modelo y las dependencias críticas están listos; devuelve "no disponible" si no lo están. |

La respuesta de inferencia contiene: probabilidad de incumplimiento, decisión de riesgo, umbral y versión del modelo. La decisión de riesgo no es la aprobación final del préstamo.

Excluyan de las entradas la etiqueta y los identificadores; si necesitan correlación, usen un identificador separado.

Validen tipos, categorías, faltantes permitidos y rangos, con errores claros ante entradas inválidas. Usen artefactos propios y un entorno de dependencias compatible con el entrenamiento.

---

## 9. Seguridad, idempotencia e importación masiva

| Tema | Requisito |
| --- | --- |
| **Autenticación y autorización (Opcional)** | Roles cliente y administrador. Un cliente solo accede a sus propias solicitudes. Las operaciones internas también se protegen; no basta con confiar en un `cliente_id` recibido. |
| **Secretos** | Fuera del repositorio. Endpoints de administración restringidos. Para la demo se permite emitir tokens de prueba de forma controlada, sin crear un quinto servicio. |
| **Idempotencia HTTP** | Misma clave + mismo contenido $\rightarrow$ misma solicitud. Misma clave + contenido distinto $\rightarrow$ conflicto (HTTP 409). Una restricción durable en base de datos impide duplicados concurrentes. |
| **Idempotencia de mensajes** | Registren el identificador procesado y el efecto de negocio en una misma transacción local. Confirmen el mensaje u offset después de confirmar los cambios. |
| **Publicación confiable** | Implementen *transactional outbox* (o un mecanismo equivalente demostrado) para no perder publicaciones si hay una caída entre guardar el estado y enviar el mensaje. No asuman transacciones distribuidas. |
| **Importación CSV de clientes** | Reporta insertados, actualizados/rechazados y errores por fila. Definan la política de actualización y una clave externa única. Importar dos veces el mismo archivo no duplica clientes. Pueden adaptar los campos de cliente del histórico entregado. |

---

## 10. Frontend obligatorio para probar la aplicación

Implementen un frontend web funcional, con la tecnología que elijan, integrado con las APIs reales. La demostración se hace desde el navegador. No se aceptan pantallas que simulen respuestas, aprobaciones o cambios de inventario sin ejecutar las operaciones del backend.

### Pantallas y funciones mínimas:

| Módulo | Debe permitir |
| --- | --- |
| **Acceso y roles (Opcional)** | Inicio y cierre de sesión, identificación del usuario y vistas diferenciadas de cliente y administrador (la autorización también se valida en el backend). |
| **Catálogo** | Listado y detalle de productos con precio; selección de cantidad y plazo para solicitar financiación. El administrador crea, actualiza y desactiva productos. |
| **Clientes** | Registro y edición de datos permitidos. Vista administrativa para consultar clientes e importar el CSV, mostrando el resumen de filas procesadas y errores. |
| **Solicitud de préstamo** | Formulario validado y confirmación con identificador. Indicar que la decisión está pendiente; evitar envíos duplicados y conservar la clave de idempotencia al reintentar. |
| **Seguimiento** | Consulta de solicitudes propias: estado, resultado de la evaluación y motivo de rechazo o cancelación. Actualización automática (polling u otro mecanismo). Un riesgo favorable no se presenta como aprobación final. |
| **Inventario (admin)** | Consulta de existencias, reservas y movimientos; registro de entradas; confirmación de entrega y cancelación con liberación de reserva. |
| **Modelo (admin)** | Versión activa, run ID y umbral. Enlace documentado a la interfaz de MLflow (no hay que reconstruir MLflow en el frontend). |

### Requisitos transversales:
* Estados de carga, mensajes de éxito y error comprensibles, validación de formularios y manejo de sesión vencida.
* Usable en computador y adaptable a pantalla móvil. No se exige identidad visual elaborada, pero sí navegación clara y formularios legibles.
* El navegador solo se comunica con las APIs autorizadas: no accede a bases de datos, Redis o el broker, ni carga el modelo de ML. URLs de servicios y orígenes permitidos (CORS) configurables; sin credenciales ni secretos en el código del frontend.
* La demostración desde el frontend debe cubrir: préstamo aprobado, rechazo por riesgo, falta de inventario, cancelación, entrega, actualización de un precio, importación de clientes y versión del modelo utilizado. Las pruebas de fallos, concurrencia, caché y reentrega de mensajes se complementan con scripts, registros y métricas, observando el resultado final en la interfaz.

---

## 11. Requisitos obligatorios y opcionales

| Obligatorio | Opcional (no suma si falta algo obligatorio) |
| --- | --- |
| • 4 microservicios con bases de datos separadas<br>• Flujo de financiación completo con estados<br>• Kafka o RabbitMQ en el flujo real + decisión documentada<br>• Redis cache-aside con mediciones<br>• Ciclo MLOps A–F con MLflow<br>• Seguridad, idempotencia y outbox<br>• Frontend integrado con roles<br>• Docker Compose reproducible | • Rate limiting con Redis<br>• CI automatizado (GitHub Actions u otro)<br>• Registro de modelos con alias en MLflow<br>• Dashboards de métricas (Prometheus/Grafana)<br>• Pruebas de carga más allá de lo exigido |

---

## 12. Pruebas de aceptación

Cada caso debe poder demostrarse durante la sustentación:

| # | Caso | Evidencia esperada |
| --- | --- | --- |
| 1 | **Riesgo favorable con existencias** | Reserva confirmada, préstamo aprobado y entrega simulada coherente. |
| 2 | **Solicitud rechazada** | Registro de la decisión y versión del modelo; no hay reserva. |
| 3 | **Riesgo favorable sin existencias** | Cancelación por falta de stock; no hay inventario negativo. |
| 4 | **Dos solicitudes por la última unidad** | Solo una obtiene la reserva. |
| 5 | **Misma petición y mismo evento repetidos** | Un préstamo y un único efecto sobre el inventario. |
| 6 | **Caída del consumidor o del broker** | Recuperación sin perder solicitudes confirmadas ni duplicar efectos. |
| 7 | **Cancelación y evento tardío** | Estado coherente, reserva liberada y préstamo no reactivado. |
| 8 | **Redis vacío, expirado o caído** | Caché demostrable y consultas recuperables desde la base de datos. |
| 9 | **Precio modificado** | Invalidación de caché y monto del préstamo basado en la cotización vigente. |
| 10 | **Modelo exportado vs. API** | Predicciones equivalentes y versión identificable. |
| 11 | **Promoción y rollback** | Cambio entre dos versiones conservando trazabilidad. |
| 12 | **Importar el mismo CSV dos veces** | No se duplican clientes. |
| 13 | **Cliente accede a préstamos ajenos** | Petición rechazada por autorización. |
| 14 | **Flujo de negocio desde el frontend** | Operaciones reales de catálogo, clientes, préstamos e inventario, con cambios persistidos. |
| 15 | **Solicitud pendiente y respuesta asíncrona** | La interfaz muestra el estado pendiente y se actualiza al recibir el resultado. |
| 16 | **Formulario inválido, sesión vencida o API caída** | Mensajes claros y estado recuperable, sin simular resultados exitosos. |

---

## 13. Entregables

| # | Entregables | Contenido mínimo |
| --- | --- | --- |
| 1 | **Repositorio Git** | Los cuatro servicios, el frontend, entrenamiento, pruebas, dependencias reproducibles y documentación. `README` con integrantes y responsabilidades. |
| 2 | **Docker Compose** | Levanta frontend, servicios, broker, Redis, bases de datos y MLflow, con volúmenes persistentes para los datos durables. |
| 3 | **Documentación de arquitectura** | Diagrama de arquitectura y de secuencia; contratos REST y de mensajes; máquina de estados; decisión Kafka/RabbitMQ. |
| 4 | **Artefactos de ML** | Scripts de preparación y particiones, historial de MLflow, informe de selección y modelo exportado con manifiesto. |
| 5 | **Guía de demostración** | Cuentas de prueba de cliente y administrador; pasos para ejecutar el flujo completo desde el navegador. |
| 6 | **Informe de Redis y desempeño** | Uso de la caché, mediciones de carga, comportamiento ante fallos y recursos consumidos. |
| 7 | **Instrucciones de reproducción** | Desde un clon limpio: comandos, puertos, configuración inicial y cómo conservar los experimentos. |

> No se exige despliegue pago en la nube.

---

## 14. Sustentación

* Los cuatro integrantes deben estar presentes. La demostración se ejecuta a partir de lo entregado en el repositorio.
* El grupo presenta la arquitectura, ejecuta el flujo desde el frontend y demuestra las pruebas de aceptación que el profesor solicite.
* El profesor puede hacer preguntas a cualquier integrante sobre cualquier parte del sistema. Si un integrante no logra explicar el trabajo entregado, su nota individual puede ser menor que la del grupo.

---

## 15. Rúbrica de evaluación

La nota se calcula como la suma ponderada de ocho criterios. Cada criterio se califica en uno de cuatro niveles; el porcentaje del nivel se multiplica por el peso del criterio.

| Nivel | Porcentaje del peso | Descripción general |
| --- | --- | --- |
| **Excelente** | 100 % | Cumple todo lo exigido, funciona en la demostración y está bien justificado y documentado. |
| **Satisfactorio** | 75 % | Cumple lo esencial y funciona; hay omisiones menores en casos borde, evidencia o documentación. |
| **En desarrollo** | 40 % | Implementación parcial: funciona solo en el caso feliz o falta evidencia de partes importantes. |
| **Insuficiente** | 0 % | No se implementó, no funciona en la demostración o es una simulación. |

### 15.1 Pesos por criterio

| # | Criterio | Peso |
| --- | --- | --- |
| 1 | Cuatro microservicios y flujo de negocio completo | 15 % |
| 2 | Broker implementado y elección justificada | 15 % |
| 3 | Redis: uso, invalidación, fallos y medición | 10 % |
| 4 | Datos, experimentación, selección y trazabilidad MLOps | 15 % |
| 5 | Exportación, API, promoción y rollback del modelo | 15 % |
| 6 | Seguridad, idempotencia, consistencia y recuperación | 15 % |
| 7 | Frontend integrado: flujo completo, roles, estados y errores | 10 % |
| 8 | Documentación y demostración reproducible | 5 % |
| | **Total** | **100 %** |

---

### 15.2 Descriptores por criterio

#### 1. Microservicios y flujo de negocio (15 %)
* **Excelente (100 %):** Cuatro servicios con responsabilidades y datos separados; flujo completo con todos los estados, HTTP 202, cotización vigente guardada, máquina de estados documentada incluyendo vencimiento y eventos tardíos.
* **Satisfactorio (75 %):** Cuatro servicios y flujo completo; faltan detalles como vencimiento de reservas o documentación de tiempos de espera.
* **En desarrollo (40 %):** Flujo funciona solo en el caso feliz, o hay acceso directo a tablas de otro servicio, o faltan estados.
* **Insuficiente (0 %):** Menos de cuatro servicios, monolito disfrazado o flujo que no llega a aprobar/rechazar.

#### 2. Broker (15 %)
* **Excelente (100 %):** El broker transporta comandos y eventos reales; contratos JSON versionados; reintentos limitados y dead letter funcionando; decisión de arquitectura sólida que responde las seis preguntas.
* **Satisfactorio (75 %):** Broker en el flujo real con contratos; reintentos o dead letter incompletos, o decisión poco profunda.
* **En desarrollo (40 %):** Broker instalado pero solo en parte del flujo, o sin manejo de errores, o decisión sin comparación real.
* **Insuficiente (0 %):** Sin broker, ejemplo aislado o comunicación síncrona en su lugar.

#### 3. Redis (10 %)
* **Excelente (100 %):** Cache-aside correcto; claves, TTL e invalidación documentados; demostración de miss, hit, expiración, invalidación y caída; mediciones p50/p95 y tasa de aciertos bien analizadas; precio del préstamo validado contra la fuente de verdad.
* **Satisfactorio (75 %):** Caché funcional y demostrada; mediciones incompletas o análisis superficial.
* **En desarrollo (40 %):** Caché sin invalidación correcta o sin tolerancia a caída de Redis; sin mediciones.
* **Insuficiente (0 %):** Redis no se usa o solo se instala.

#### 4. Datos y experimentación MLOps (15 %)
* **Excelente (100 %):** EDA, hash del dataset, particiones estratificadas y reproducibles, pipeline sin fuga de datos; baseline + 3 algoritmos + 6 corridas en MLflow con todos los metadatos; métrica de selección predefinida; umbral justificado con costos; prueba usada solo al final.
* **Satisfactorio (75 %):** Cumple lo anterior con omisiones menores (p. ej., falta calibración o algún metadato).
* **En desarrollo (40 %):** Menos algoritmos o corridas, selección por accuracy, metadatos incompletos o posible fuga de datos.
* **Insuficiente (0 %):** Sin MLflow, sin particiones correctas o modelo entrenado con la etiqueta o los identificadores.

#### 5. Exportación, API y ciclo de versiones (15 %)
* **Excelente (100 %):** Pipeline completo exportado con manifiesto; promoción explícita; API con los seis endpoints, validación de entradas y carga al iniciar; equivalencia demostrada; monitoreo y drift simulado; segunda versión, promoción y rollback funcionando.
* **Satisfactorio (75 %):** API y exportación correctas; rollback o monitoreo incompletos.
* **En desarrollo (40 %):** API carga "el último archivo", faltan endpoints o no hay segunda versión.
* **Insuficiente (0 %):** El modelo no se sirve desde Préstamos o se entrena por petición.

#### 6. Seguridad, idempotencia y recuperación (15 %)
* **Excelente (100 %):** Roles y autorización validados en backend; idempotencia HTTP (incluye 409) y de mensajes con restricciones durables; outbox demostrado; reserva atómica sin stock negativo; recuperación ante caídas; importación CSV idempotente.
* **Satisfactorio (75 %):** Cumple lo esencial; algún caso de aceptación de esta categoría falla o no se demuestra.
* **En desarrollo (40 %):** Idempotencia solo en memoria o en Redis, sin outbox, o autorización solo en el frontend.
* **Insuficiente (0 %):** Sin autenticación, duplicados en concurrencia o inventario negativo.

#### 7. Frontend (10 %)
* **Excelente (100 %):** Todos los módulos de la sección 10 integrados con APIs reales; roles, estados pendientes con actualización automática, errores y sesión vencida bien manejados; adaptable a móvil.
* **Satisfactorio (75 %):** Flujo completo funcional; detalles menores de usabilidad, validación o diseño responsivo.
* **En desarrollo (40 %):** Faltan módulos importantes (inventario, importación o seguimiento) o no maneja errores.
* **Insuficiente (0 %):** Sin frontend o con respuestas simuladas.

#### 8. Documentación y reproducibilidad (5 %)
* **Excelente (100 %):** Arranca con `docker compose up` desde un clon limpio; README, diagramas, contratos y guía de demo completos; contribuciones de los 4 integrantes visibles.
* **Satisfactorio (75 %):** Reproducible con ajustes menores; documentación con vacíos pequeños.
* **En desarrollo (40 %):** Requiere pasos no documentados o la documentación es escasa.
* **Insuficiente (0 %):** No es posible levantar el sistema con lo entregado.

---

### 15.3 Condiciones que afectan la nota

* Si el sistema no se puede levantar con lo entregado en el repositorio, la demostración se limita a lo que funcione y los criterios afectados se califican según esa evidencia.
* Funcionalidades simuladas (respuestas quemadas en el frontend, aprobaciones sin reserva real, broker no usado) se califican como Insuficiente en el criterio correspondiente.
* Secretos o credenciales en el repositorio implican como máximo "En desarrollo" en el criterio 6.
* Las extensiones opcionales no compensan requisitos obligatorios faltantes.
* La nota individual puede ajustarse según el desempeño en la sustentación y la evidencia de contribución en el repositorio (sección 14).

---

## 16. Documentación oficial de apoyo

* **Kafka:** [https://kafka.apache.org/documentation/](https://kafka.apache.org/documentation/)
* **RabbitMQ, fiabilidad:** [https://www.rabbitmq.com/docs/reliability](https://www.rabbitmq.com/docs/reliability)
* **Redis, cache-aside:** [https://redis.io/docs/latest/develop/use-cases/cache-aside/](https://redis.io/docs/latest/develop/use-cases/cache-aside/)
* **MLflow Tracking:** [https://mlflow.org/docs/latest/ml/tracking/](https://mlflow.org/docs/latest/ml/tracking/)
* **scikit-learn, errores comunes:** [https://scikit-learn.org/stable/common_pitfalls.html](https://scikit-learn.org/stable/common_pitfalls.html)
* **scikit-learn, persistencia:** [https://scikit-learn.org/stable/model_persistence.html](https://scikit-learn.org/stable/model_persistence.html)
* **FastAPI, carga del modelo al iniciar:** [https://fastapi.tiangolo.com/advanced/events/](https://fastapi.tiangolo.com/advanced/events/)
* **Flask, API JSON:** [https://flask.palletsprojects.com/en/stable/quickstart/](https://flask.palletsprojects.com/en/stable/quickstart/)