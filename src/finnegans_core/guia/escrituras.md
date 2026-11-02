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

## El alta ignora el Codigo que mandás
Verificado contra la API real (alta de `cliente`): en un POST Finnegans
**ignora el `Codigo` del body** y le asigna su propio código al registro nuevo.
Lo devuelve en `id` de la respuesta (`{"id": "2956", "message": "created"}`).
`escribir` relee el registro con ese código y te dice cuál le asignó (y si es
distinto del que mandaste). Para modificarlo o borrarlo después usá ese código:
el que mandaste en el body no existe.

## Campos obligatorios que el swagger no marca
El POST de `cliente` falla (HTTP 500) si faltan estos dos campos, aunque el
swagger no los marque como requeridos:
- `CategoriaFiscalCodigo` ("Debe indicar la categoría fiscal"). Valores de
  `categoriaFiscal/list`: RI, EX, MO, CF, DEX, RFactM, IVARI, FCEGRANRI,
  FCEEXENTO, "CF DEMO", "Sin identificación".
- `IdentificacionTributariaCodigo` ("Falta especificar Identificación
  Tributaria"). Valores de `identificacionTributaria/list`: SINIDENTIFICACION,
  CUIT, DNI, CUIL, CUITE, PAS.

Son decisiones fiscales: **preguntale al usuario cuál corresponde**, nunca la
elijas vos. Con CF + SINIDENTIFICACION no hizo falta número. Con CUIT, DNI u
otro tipo con número, presumiblemente también hace falta
`IdentificacionTributariaNumero`.

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
- Producción: no hay host de pruebas.
