# Parámetros de reportes (viewers)

Los viewers son `GET /api/reports/{Nombre}` y solo llevan parámetros de query.

## Nombres
Son inconsistentes: mayormente `PARAMWEBREPORT_*`, pero también `PARAM*`, sin
prefijo, y variantes de mayúsculas (`Moneda` / `moneda`). Pasalos **exactamente**
como los escribe el swagger (prefijo y mayúsculas incluidos); `ver_endpoint` los
lista.

## Fechas
Formato `yyyy-MM-dd` o constantes relativas:
`getCurrentDate`, `getFirstDayOfWeek`, `getFirstDayOfMonth`,
`getLastDayOfMonth`, `getFirstDayOfYear`, `getLastDayOfYear`,
`getFirstDayOfLastMonth`, `getLastDayOfLastMonth`, `getFirstDayOfLastWeek`,
`getLastDayOfLastWeek`, `getFirstDayOfLastYear`, `getLastDayOfLastYear`.
Para "el mes pasado": desde `getFirstDayOfLastMonth` hasta
`getLastDayOfLastMonth`.

## Parámetros de código
Aceptan un código o `arbol(nombre)`: selección inteligente que busca primero
como árbol y después como nodo.

## Gemelos DEALS
11 viewers tienen un gemelo `…DEALS`, una variante para la app Deals. Elegí el
que corresponda al origen de los datos.

## Columnas
El esquema de salida suele no estar documentado; las columnas se conocen
después de llamar. `leer` carga el resultado en el workspace e informa las
columnas; después usá `consultar` o `exportar`.

## Si falta algo
Si el pedido necesita sucursal, unidad de negocio o rango de fechas y el usuario
no lo dijo, preguntá (tema `sucursales`). Nunca asumas una sucursal.
