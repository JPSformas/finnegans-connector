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
- Alta de cliente (POST): Finnegans ignora el `Codigo` del body, asigna su
  propio código y lo devuelve en `id` (`escribir` te lo informa). Usá ese código
  para leerlo, modificarlo o borrarlo.
- El alta exige `CategoriaFiscalCodigo` (RI, EX, MO, CF, DEX, RFactM, IVARI,
  FCEGRANRI, FCEEXENTO, "CF DEMO", "Sin identificación") e
  `IdentificacionTributariaCodigo` (SINIDENTIFICACION, CUIT, DNI, CUIL, CUITE,
  PAS), aunque el swagger no los marque requeridos. Preguntale al usuario cuáles
  corresponden: es una decisión fiscal. Con CUIT o DNI presumiblemente hace falta
  también `IdentificacionTributariaNumero`.
- Para modificar un cliente: tema `escrituras`. Para IIBB: tema `iibb`.
