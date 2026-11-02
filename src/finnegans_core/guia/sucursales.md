# Sucursales y unidades de negocio (SOUTEX / Formas)

Se opera por **sucursal**. Códigos reales (de `sucursal/list`):

| Código | Sucursal | Uso |
|---|---|---|
| `EMPRE01` | Formas Publicitarias SA | Productiva |
| `4` | Soutex SA | Productiva |
| `7` | FP DEMO | Interna / gestión alternativa |
| `6` | ST Demo | Interna / gestión alternativa |
| `5` | Prueba | Interna |

Las dos compañías reales son **Formas Publicitarias SA** y **Soutex SA**
(cada una con su variante DEMO para asuntos internos).

## Unidades de negocio de Formas Publicitarias SA
Sub-dimensión de la sucursal: "Formas Shop", "Corporate", "No Estrés".
Cómo filtrar cada una: a completar con el uso.

## Cuándo preguntar
- Si el pedido necesita sucursal, unidad de negocio o rango de fechas y el
  usuario no lo dijo, preguntá antes de consultar y ofrecé las opciones de esta
  tabla.
- Nunca asumas una sucursal por defecto.

## Producción real
El servidor es producción: no hay host de pruebas. Ya hay artefactos de prueba
cargados (`AjusteDeStockPruebaServidorSQL`, `reports/PruebaIsmaStock`). Las
sucursales 7, 6 y 5 son internas, no un entorno aislado de la API.
