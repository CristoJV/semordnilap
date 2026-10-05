# Semordnilap

Pipeline reproducible para construir n-gramas con información contextual UPOS
en español y gallego.

```mermaid
flowchart LR
    H[Wikisource revision] --> C[Corpus shards]
    C --> T[Stanza ES/GL]
    T --> U[UD v2 gzip shards]
    U --> N[Streaming n-grams]
    N --> D[(DuckDB generations)]
    D --> S[Optional search]
```

## Superficie soportada

```text
sp_corpus_wikisource   descarga corpus versionados
sp_tag                 descarga modelos, smoke tests y tagging contextual
sp_ngrams              extracción, migración, inspección y exportación
sp_search_ngrams       consumidor opcional de semordnilaps
```

Instalación y comprobación:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

El flujo completo, desde la descarga hasta la extracción, está en la
[guía del pipeline](docs/guides/pipeline.md). La
[arquitectura técnica](docs/technical/README.md) describe identidades,
manifiestos, recuperación y almacenamiento.

Las decisiones principales son:

- la puntuación se conserva por defecto y las ventanas pueden cruzar frases,
  pero nunca documentos;
- el tagging se realiza sobre el contexto completo o sobre fragmentos largos
  con límites explícitos y offsets globales;
- el formato actual es UD JSONL v2 comprimido y dividido en shards; el lector
  mantiene compatibilidad con v1;
- cada artefacto final tiene manifiesto, checksums e identidad inmutable;
- reintentar extracción no duplica recuentos y cambiar una política crea otra
  identidad;
- `ñ` sólo se pliega a `n` cuando se solicita expresamente.

Documentación: [mapa](docs/README.md), [ADRs](docs/adr/README.md),
[RFC implementado](docs/rfc/0001-core-pipeline-hardening.md) y
[plan de implementación](docs/plan/0002-core-pipeline-hardening.md).
