# Conector Finnegans para usuarios no técnicos — Diseño (Nivel 3)

**Fecha:** 2026-08-05
**Estado:** Aprobado, listo para plan de implementación
**Proyecto:** `finnegans-connector` (empresa: SOUTEX)

## Objetivo

Permitir que ~20 usuarios no técnicos (Administración, Ventas, Marketing,
Producción, Compras) **consulten y modifiquen** datos del ERP Finnegans en
lenguaje natural, a través de Claude Desktop, con una salvaguarda robusta
de confirmación humana en cada escritura.

## Contexto y hallazgos del PoC existente

Existe un PoC (`finnegans-connector`) hecho con IA. Estado real verificado:

- **Autenticación al ERP: funciona** (`client_credentials` → token, con caché
  y reintento en 401/403).
- **Descubrimiento de APIs: roto en runtime.** El proceso MCP conectado tira
  `asyncio.run() cannot be called from a running event loop`. Causa raíz: el
  código en disco ya fue refactorizado a `async` correctamente
  (`discovery.py`, `server.py`), pero **el proceso MCP en ejecución corre una
  versión vieja** — nunca se reinició. `asyncio.run()` solo queda en
  `verify_setup.py`, donde es correcto (corre como script suelto).
- Estructura del código **bien separada** (`config`/`client`/`discovery`/
  `validator`/`server`): se construye sobre ella, no se reescribe.
- La confirmación de escritura actual es **Nivel 1**: el resumen que ve el
  usuario es texto libre redactado por Claude (`descripcion`), y
  `ejecutar_cambio` confía en que Claude pase `usuario_confirmo=true`.

## Decisiones de diseño (locked)

| Dimensión | Decisión |
|---|---|
| Alcance | (C) Lectura + escritura abiertas, con confirmación por cada escritura. |
| Despliegue | (A) MCP local en Python, en Claude Desktop de cada usuario, preconfigurado. |
| Identidad/auth | (B) Credencial de servicio **compartida**, ~20 usuarios. |
| Seguridad de escritura | **Nivel 3**: vista previa estructurada + lista negra + verificación posterior. |
| Estrategia | Enfoque 1: **evolucionar** el PoC (no reescribir). Enfoque 2 (tools curadas) = fase futura. |

### Condiciones obligatorias de la opción (B)

1. La credencial de servicio debe tener **rol acotado** en Finnegans (NO admin).
   Es la única muralla que no depende del comportamiento de Claude o del usuario.
2. Cada instalación lleva **identidad de operador** para reconstruir la
   trazabilidad en la capa del conector (el ERP solo verá "el bot").

## Arquitectura

### Se conserva
- Separación en módulos y modelo de 6 tools (`buscar_api`, `ver_api`,
  `consultar_finnegans`, `preparar_cambio`, `ejecutar_cambio`,
  `verificar_conexion`).
- Cliente HTTP en librería estándar (auditable), caché de token, reintento auth.

### Se arregla
- **Descubrimiento:** reiniciar el servidor MCP para correr la versión `async`
  de disco y **verificar** que `buscar_api`/`ver_api` devuelven resultados
  reales contra el catálogo. Errores del MCP de docs deben ser claros y no
  romper el resto del flujo.

### Se agrega / amplía
| Módulo | Cambio |
|---|---|
| `config.py` | `FINNEGANS_OPERATOR`, `AUDIT_LOG_PATH`, lista de operaciones de alto riesgo. |
| `validator.py` | Flujo de confirmación reescrito a Nivel 3. |
| `audit.py` (nuevo) | Log append-only JSONL con operador, hora, endpoint, datos, resultado. |
| `server.py` | `preparar_cambio`/`ejecutar_cambio` devuelven vista estructurada y exigen código de confirmación. |

Las **lecturas** (`consultar_finnegans`) no cambian su flujo.

## Flujo de escritura Nivel 3

1. **Vista previa estructurada y verificada (no prosa de Claude).**
   `preparar_cambio` trae el spec del endpoint (vía discovery, cacheado) y arma
   una tabla campo por campo: método, endpoint real, recurso/id afectado, y cada
   campo del body con su etiqueta oficial del spec y el valor propuesto.
   - Valida el body contra `requestBodySchema`: campos requeridos presentes,
     tipos plausibles.
   - Marca con ⚠️ los campos que Claude envió pero **no existen en el schema**
     (señal de invención).
   - Esa tabla verificada ES el resumen que ve el usuario.

2. **Lista negra / alto riesgo.**
   - **DELETE bloqueado por defecto** (habilitable por config).
   - PUT/DELETE **sin `id`** → potencialmente masivo → alto riesgo.
   - Endpoints/patrones sensibles configurables en `config`.
   - Alto riesgo ⇒ preview en rojo y código de confirmación obligatorio.

3. **Código de confirmación (freno anti-atajo).**
   `preparar_cambio` genera un código corto (ej. 4 dígitos) mostrado en el
   preview. `ejecutar_cambio` exige `codigo_confirmacion` que **el humano tipea
   de vuelta**. Obliga a un turno humano explícito y deja rastro de auditoría.
   - **Limitación honesta:** como Claude ve todo lo que pasa por las tools, este
     código eleva la barrera y crea evidencia, pero **no es un gate que Claude no
     pueda técnicamente saltear**. El gate infalsificable real es el Enfoque 3
     (aprobación fuera de Claude), disponible como add-on futuro solo para
     DELETE / operaciones masivas.

4. **Verificación posterior (read-back).**
   - POST/PUT → GET del registro afectado, mostrar estado resultante.
   - DELETE → GET que confirme 404.

Todos los pasos (preparado / ejecutado / rechazado / error) se registran en el
audit log.

## Auditoría e identidad de operador

- **Identidad por instalación:** `FINNEGANS_OPERATOR` en el `.env`. Es lo único
  distinto entre las 20 instalaciones; las credenciales de servicio son idénticas.
- **`audit.py`:** archivo JSONL append-only local. Cada evento registra:
  timestamp, operador, tipo de evento, método, endpoint, id, params, body,
  `confirmacion_id`, si se tipeó el código, resultado y estado leído en la
  verificación posterior.
- **Regla de oro:** el log NUNCA guarda token ni `client_secret`.
- **Futuro (no en piloto):** enviar los logs a una carpeta de red o endpoint
  central para auditoría unificada de los 20.

## Distribución y testing

### Paquete de instalación
1. Carpeta única con el conector + `install.py`/`.bat` que: pide el nombre del
   operador, escribe el `.env` (credenciales de servicio embebidas) y registra
   el server en `claude_desktop_config.json` automáticamente.
2. Corre `verify_setup.py` mostrando ✅/❌: credenciales API, catálogo de docs,
   tool registrada.
3. `ASSISTANT_INSTRUCTIONS.md` (instrucciones de proyecto en Claude Desktop)
   actualizado al flujo Nivel 3.

### Testing
- **Unit:** `validator.py` (vista estructurada, campos ⚠️, bloqueo DELETE,
  código de confirmación), `audit.py` (escritura correcta, nunca secretos).
- **Integración con stub:** servidor Finnegans falso local para el ciclo
  completo prepare→confirmar→ejecutar→read-back sin tocar el ERP real.
- **Smoke test real** (`examples/smoke_test.py`): primero solo lecturas; luego
  UNA escritura controlada en un registro descartable.
- **Criterio de listo:** `verificar_conexion` todo OK, una lectura real anda, y
  una escritura de prueba pasa por confirmación + read-back correctamente.

## Fuera de alcance (fases futuras)

- Enfoque 2: tools curadas por área para operaciones frecuentes/peligrosas.
- Gate externo (Enfoque 3) para DELETE / operaciones masivas.
- Auditoría centralizada de las 20 instalaciones.
- Credenciales por usuario (migrar de B a A) si el piloto escala.
