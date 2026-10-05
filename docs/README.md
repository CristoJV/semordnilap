# Documentación

- [Guía completa del pipeline](guides/pipeline.md): descarga, modelos,
  tagging, resume, extracción y exportación.
- [Operación de n-gramas](guides/ngrams.md): identidades, DuckDB, migración y
  mantenimiento.
- [Búsqueda opcional](guides/search.md): consumo de generaciones finales.
- [Arquitectura técnica](technical/README.md): componentes y contratos.
- [ADRs](adr/README.md): decisiones aceptadas.
- [RFC 0001](rfc/0001-core-pipeline-hardening.md): auditoría y resultado.
- [Plan ejecutado](plan/0002-core-pipeline-hardening.md): fases y pruebas.

El alcance soportado es `corpus -> tagging contextual -> n-gramas`, con la
búsqueda DuckDB como consumidor opcional. La documentación histórica de las
aplicaciones eliminadas permanece en [legacy](legacy/README.md), pero su código,
entry points y dependencias ya no forman parte del proyecto.
