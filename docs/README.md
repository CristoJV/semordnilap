# Documentación

- [Guía completa del pipeline](guides/pipeline.md): descarga, extracción
  directa, resume y exportación.
- [Operación de n-gramas](guides/ngrams.md): identidades, DuckDB, migración y
  mantenimiento.
- [Búsqueda opcional](guides/search.md): consumo de generaciones finales.
- [Arquitectura técnica](technical/README.md): componentes y contratos.
- [ADRs](adr/README.md): decisiones aceptadas.
- [RFC 0001](rfc/0001-core-pipeline-hardening.md): auditoría y resultado.
- [Plan del esquema textual v3](plan/0004-text-only-ngram-schema-v3.md):
  migración, fases y pruebas.

El flujo de n-gramas soportado es `corpus -> n-gramas textuales`, con la
búsqueda DuckDB como consumidor opcional. `sp_tag` es una utilidad separada:
los corpus UD etiquetados no son entrada de `sp_ngrams`. La documentación
histórica de las aplicaciones eliminadas permanece en
[legacy](legacy/README.md), pero su código, entry points y dependencias ya no
forman parte del proyecto.
