# IIBB y situaciones impositivas (no está en el swagger)

`ProvinciaItems[].ControlImpositivo1` codifica la situación de IIBB por
provincia. Deducido de los mensajes de error de la API y de 45 clientes reales:

| Valor | Situación | Restricción |
|---|---|---|
| `0` | Contribuyente Local | **una sola provincia** por cliente |
| `1` | Convenio Multilateral | varias provincias |
| `3` | tercera situación, sin identificar | visto solo en clientes de una provincia |

## Reglas que la API hace cumplir (devuelve `HTTP 500`)
- Las tres situaciones no pueden coexistir en un mismo cliente.
- Solo puede haber una provincia en Contribuyente Local.

Regla práctica: un cliente con más de una provincia va con todas en `1`.

## Datos que la propia API rechaza
En una muestra de 45 clientes activos, 10 tenían provincias en situaciones
mixtas. Cualquier actualización a esos clientes falla con 500 hasta que se
normalice IIBB.

Normalizar IIBB es una **decisión fiscal**: preguntale al usuario qué valor
corresponde, no lo elijas vos.

## Efecto colateral conocido
Al pasar un cliente a Convenio Multilateral, Finnegans completa
`NroInscripcionIIBB` por su cuenta con el CUIT sin guiones. Ver el tema
`escrituras` para el procedimiento y el diff obligatorio.

## Sin vuelta atrás por API
Si el cliente venía en un estado que la API rechaza (mixto), no se puede
restaurar por API: hay que hacerlo desde la interfaz de Finnegans, que permite
guardar cosas que la API no acepta.
