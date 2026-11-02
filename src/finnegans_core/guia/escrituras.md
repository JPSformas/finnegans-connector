# Escrituras: el PUT reemplaza el registro completo

Verificado contra la API real (entidad `cliente`, 2026-09-03). Aplica a las
entidades con `PUT /api/{entidad}/{codigo}`.

- El body debe ser el **objeto completo** de la entidad, no solo los campos que
  cambian. No existe actualización parcial.
- El identificador se lee del campo `Codigo` **del body**, no del path. Si falta,
  la API responde `HTTP 406 "Not Acceptable: empty id"` aunque la URL traiga el
  código.
- `PUT ...?createIfNotExists=1` inserta si el registro no existe (upsert).
- Crear: `escribir(metodo="POST", path=..., body=...)`. Upsert:
  `escribir(metodo="PUT", ..., params={"createIfNotExists": "1"})`.

## Procedimiento (leer, modificar, escribir)
1. Cargá el registro con `leer` (queda como tabla en el workspace).
2. Usá `escribir` con `base=<tabla>` y `cambios={...}`: modifica SOLO los campos
   indicados sobre esa copia y manda el objeto completo.
3. Mostrale al usuario el diff que devuelve `escribir`: qué campos cambian y de
   qué valor a qué valor.
4. Después de escribir, comparalo contra el estado previo.

## La API escribe campos que no mandaste
Al pasar un cliente a Convenio Multilateral, Finnegans completó
`NroInscripcionIIBB` por su cuenta con el CUIT sin guiones. Nunca afirmes "solo
cambió X" sin haberlo comparado.

## Lo que se escribe no siempre se puede deshacer
Si el registro venía en un estado que la API rechaza (ver `iibb`), no se puede
volver atrás por API: hay que hacerlo por la interfaz de Finnegans.

## Antes y después de escribir
`escribir` ejecuta de inmediato (no hay vista previa). Claude Desktop puede
pedirle permiso al usuario antes de cada escritura según su configuración.
- Antes: usá `ver_endpoint(path)` para ver los campos del body y cuáles son
  requeridos; `ver_endpoint(path, campo=...)` detalla un campo puntual.
- La propia API rechaza los bodies inválidos (por ejemplo 406 "empty id", o 500
  con IIBB mixto) y `escribir` te devuelve ese error traducido a castellano
  claro. Explicáselo al usuario; un 406 "empty id" casi siempre significa que
  falta `Codigo` en el body o que armaste un body parcial.
- Después: leé el diff que devuelve `escribir` y decile al usuario qué campos
  cambiaron y cuáles cambió la API por su cuenta.

## Seguridad
- Nunca pidas ni guardes contraseñas personales.
- Operaciones de alto riesgo: leé el motivo y pedí atención extra al usuario.
- Los DELETE pueden estar bloqueados por política; si es así, explicalo.
- Producción: no hay host de pruebas.
