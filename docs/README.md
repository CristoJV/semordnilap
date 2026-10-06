# Documentación

- [Guía completa del pipeline](guides/pipeline.md): descarga, extracción raw
  directa, tagging opcional, resume y exportación.
- [Operación de n-gramas](guides/ngrams.md): identidades, DuckDB, migración y
  mantenimiento.
- [Búsqueda opcional](guides/search.md): consumo de generaciones finales.
- [Arquitectura técnica](technical/README.md): componentes y contratos.
- [ADRs](adr/README.md): decisiones aceptadas.
- [RFC 0001](rfc/0001-core-pipeline-hardening.md): auditoría y resultado.
- [Plan de adaptadores directos](plan/0003-direct-corpus-ngram-adapters.md):
  fases y pruebas.

El alcance soportado es `corpus -> n-gramas`, con `tagging contextual` como
rama opcional de enriquecimiento y la búsqueda DuckDB como consumidor
opcional. La documentación histórica de las aplicaciones eliminadas permanece
en [legacy](legacy/README.md), pero su código, entry points y dependencias ya no
forman parte del proyecto.
