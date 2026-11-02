# Tipos de endpoint

El tipo sale de la descripción del tag en el swagger, `Tipo: <X>`. Leelo de ahí,
no lo adivines por el path. El swagger global tiene 579 paths (los hosts
`j11.teamplace.finneg.com` y `oneteam.finneg.com` sirven el mismo spec).

## Viewer (234 tags)
- Reportes de solo lectura, siempre `GET /api/reports/{Nombre}`, solo parámetros
  de query.
- El esquema de salida suele ser inutilizable ("No fue posible generar un
  ejemplo"): las columnas se conocen recién al llamar. Por eso `leer` carga el
  viewer en el workspace y te informa las columnas.
- 11 tienen un gemelo `…DEALS`, una variante para la app Deals.
- Detalle de parámetros: tema `parametros`.

## EntidadVO (127 tags)
- Entidades CRUD. Registro: `GET|PUT|DELETE /api/{entidad}/{codigo}`. Crear:
  `POST /api/{entidad}`.
- Listado `GET /api/{entidad}/list`: solo 97 de las 127 lo tienen. Acepta
  `updatedSince=yyyy-mm-dd` para lecturas incrementales.
- `PUT` acepta `createIfNotExists=1`: inserta si el registro no existe (upsert).
- El schema del body es una referencia externa:
  `swaggerApi?api={entidad}&nombreVO={Entidad}VO`.
- Reglas de escritura: tema `escrituras`.

## Sin tag
`GET /oauth/token` y `custom/BProc` (el único con PATCH).

## Otros datos
- La clave de documentación del swagger va embebida en cada `$ref` del propio
  spec: es una clave de solo lectura de docs a nivel workspace, no un secreto
  personal.
