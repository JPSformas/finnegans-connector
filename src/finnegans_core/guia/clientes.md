# Clientes (`cliente/list` y maestro)

- `cliente/list` devuelve ~4.150 registros (~469.000 caracteres). No lo vuelques
  al chat: `leer` lo carga en el workspace; trabajá con `consultar` (SQL) o
  `exportar`, y ofrecé un filtro (por nombre, solo activos) o un archivo.
- El listado trae solo `codigo`, `nombre`, `descripcion` y `activo`. El resto de
  los campos hay que pedirlos cliente por cliente con `GET /api/cliente/{codigo}`
  (`leer`).
- El ERP no busca por nombre: se lista y se filtra (`consultar`).
- Los códigos conviven en tres formatos: `301`, `C02155`, `P00016`.
- El maestro tiene basura: clientes llamados `--`, `.` y varios que arrancan con
  un espacio en blanco. Al filtrar por nombre, normalizá con trim y no te
  sorprendas si aparecen.
- Para listados incrementales, `updatedSince=yyyy-mm-dd` en `/list`.
- Para modificar un cliente: tema `escrituras`. Para IIBB: tema `iibb`.
