# Convención de rutas de Finnegans

- Un registro por código: `GET /api/{entidad}/{codigo}`.
- Listado: `GET /api/{entidad}/list`.
- Reportes: `GET /api/reports/{Nombre}`.
- Crear: `POST /api/{entidad}`. Modificar: `PUT /api/{entidad}/{codigo}`.
  Eliminar: `DELETE /api/{entidad}/{codigo}`.
- `id missing` = falta el segmento del path; usá `/list` o el código.

## Cómo encontrar el endpoint correcto
1. `buscar_endpoint` con palabras del negocio (acepta sinónimos: tesorería o
   caja buscan fondos, cobrar busca cobranza o cobro, inventario busca stock,
   contabilidad busca asiento o cuenta).
2. `ver_endpoint` para ver método, parámetros y esquema del body.
3. Si la búsqueda trae una nota que dice "preguntale al usuario", preguntale
   antes de seguir.

Ojo con remito: `/remito` devuelve 501; la búsqueda lo redirige a despacho o
recepción.

## Mapeos de lenguaje natural a API
- "buscar un cliente por nombre": `cliente/list` y filtrar por nombre (el ERP
  no busca por nombre; se lista y se filtra con `consultar`). Ver `clientes`.
- "ventas / facturación de un período": reporte de ventas correspondiente
  (confirmar el endpoint con `buscar_endpoint`) con su rango de fechas. Ver
  `parametros`.

## Ejemplos por área
- Compras: órdenes de compra pendientes del proveedor X.
- Ventas: datos del cliente Y, oportunidades comerciales.
- Admin: saldo del cliente Z, composición de saldo.
- Producción: datos del producto ABC.
- Marketing: campañas, clientes, reportes de ventas.

## Errores comunes
- 404: el código o id no existe; explicá que el registro no se encontró.
- Algunos DELETE pueden estar bloqueados por política: si es así, explicalo.
