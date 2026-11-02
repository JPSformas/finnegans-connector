# Escrituras: el PUT reemplaza el registro completo

Verificado contra la API real (entidad `cliente`, 2026-09-03). Aplica a las
entidades con `PUT /api/{entidad}/{codigo}`.

- El body debe ser el **objeto completo** de la entidad, no solo los campos que
  cambian. No existe actualización parcial.
- El identificador se lee del campo `Codigo` **del body**, no del path. Si falta,
  la API responde `HTTP 406 "Not Acceptable: empty id"` aunque la URL traiga el
  código.
- `PUT ...?createIfNotExists=1` inserta si el registro no existe (upsert).
- Crear: `POST /api/{entidad}`.

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

## Advertencias confiables
El validador resuelve el schema real del body:
- "Falta el campo requerido X" en un PUT casi siempre significa que armaste un
  body parcial: volvé al procedimiento de arriba.
- "Campo desconocido X": el campo no existe en la entidad (error de tipeo o de
  nombre).
- Si dice "(sin schema: no se pudo verificar contra la documentación)", no hay
  red de seguridad: avisale al usuario.
Si hay advertencias, avisale al usuario antes de seguir.

## Seguridad
- Nunca pidas ni guardes contraseñas personales.
- Operaciones de alto riesgo: leé el motivo y pedí atención extra al usuario.
- Los DELETE pueden estar bloqueados por política; si es así, explicalo.
- Producción: no hay host de pruebas.
