# Arquitectura técnica

Estado implementado a 2026-10-06.

## Flujo de n-gramas

```mermaid
flowchart LR
    HF[HF revision] --> CA[corpus acquisition]
    CA --> CS[(source gzip shards)]
    CS --> RA[manifest-aware adapter]
    RA --> EX[raw Unicode windows]
    EX --> TX[transactional chunks]
    TX --> FG[(active DuckDB generation v3)]
    FG --> SE[optional read-only search]

    CS -. independent utility .-> ST[sp_tag / Stanza]
    ST --> UD[(UD JSONL artifacts)]
```

La rama de tagging es independiente. `sp_ngrams` no importa su modelo de
dominio, no lee `ud-jsonl` y no persiste UPOS.

| Capa | Módulos | Responsabilidad |
|---|---|---|
| Corpus | `corpus/{cli,wikisource,corpusnos}.py` | selección, export streaming, shards, revisión y resume |
| N-gram domain | `ngrams/domain/*` | tokenización Unicode, ventanas, filtros y normalización |
| N-gram application | `ngrams/application/*` | identidad, chunks, resume y exportación |
| Source adapters | `ngrams/infrastructure/corpus_adapters.py` | resolución segura de colecciones, idioma y shards |
| Storage | `ngrams/infrastructure/repositories.py` | esquema v3, migraciones y generaciones DuckDB |
| Search | `search/*` | consumidor opcional sólo lectura |
| Tagging | `tagging/*` | utilidad UD independiente, sin integración con n-gramas |
| Shared | `utils/artifacts.py`, `utils/io.py`, `utils/text.py` | checksums, locks, manifests e I/O |

## Artefactos e identidad

Los corpus gestionados tienen manifiesto versionado, estado, configuración,
checksums, procedencia y `artifact_id`. Un manifiesto de colección enumera de
forma autoritativa sus hijos; los adaptadores no consumen directorios `.part`,
artefactos incompletos ni hijos no declarados.

`dataset_id` deriva del artefacto fuente, el hash de política, idioma y alias
de corpus. `chunk_id` identifica un segmento determinista. Cambiar una opción
semántica crea otra identidad y repetir un chunk ya confirmado es un no-op.

La búsqueda exporta un `pair_id` ligado a los alias de corpus y un
`lexical_pair_id` independiente de ellos. Ambos usan la superficie canónica,
son insensibles a caja y no dependen de frecuencias ni de `dataset_id`. Los
IDs de dataset se exportan por separado para conservar la procedencia exacta
sin impedir comparaciones entre nuevas muestras del mismo corpus.

## Ventanas y superficie

El extractor recorre spans lexicales Unicode sobre cada documento fuente. Una
deque de tamaño `max_n` permite ventanas que atraviesen puntuación y límites
de frase, pero se vacía al terminar cada documento. La superficie comprende
desde el primer token léxico hasta el final del último y conserva la puntuación
intermedia.

- `surface_key`: NFC, case-folding Unicode y espacios colapsados;
- `surface_display`: grafía de origen con espacios normalizados;
- `norm_key`: clave compacta sin puntuación ni acentos para invertir;
- `has_punctuation`: presencia de puntuación en la superficie.

No existe una propiedad `crosses_sentence`: sin tagging no hay un límite de
frase anotado fiable, y la superficie ya permite observar la puntuación.

## DuckDB schema v3

```mermaid
erDiagram
    extraction_datasets ||--o{ extraction_runs : owns
    extraction_datasets ||--o{ extraction_chunks : commits
    extraction_chunks ||--o{ ngram_stage_v2 : stages
    extraction_datasets ||--o{ ngram_final_v2 : activates
```

Los sufijos `_v2` de las tablas de generación se mantienen para preservar los
datos existentes; la versión del esquema global es 3. Cada chunk confirma en
una transacción sus recuentos textuales, ledger y cursor. La finalización agrega
una generación, la activa y retira staging en otra transacción.

Las tablas legacy `ngram_counts`, `ngram_totals` y `ngram_compactions` siguen
disponibles. Tanto ellas como las tablas de generación almacenan
`has_punctuation` en las filas textuales.

## Migración

Una apertura de escritura exige esquema actual. La única actualización
permitida es explícita:

```bash
uv run sp_ngrams db migrate --db-path DB
```

La migración se ejecuta en una transacción. Para v0/v1 crea las estructuras
que falten y añade `has_punctuation=false`. Para v2 preserva tablas y filas
textuales y elimina las cuatro relaciones UPOS legacy/staging/final. Registrar
v3 por segunda vez no duplica ni altera datos. Una versión superior a 3 se
rechaza incluso en modo de lectura para evitar interpretaciones incompatibles.

## Límites y recuperación

| Etapa | Límite principal | Recuperación |
|---|---|---|
| Corpus | fila + shard actual | último shard confirmado |
| Extracción | deque `max_n` + contador configurado | último documento/segmento transaccional |
| Finalización | temporales administrados por DuckDB | rollback de generación |
| Exportación | una fila + buffer de archivo | final anterior intacto |

## Verificación

```bash
uv run pytest -q
uv run ruff check .
```

Las pruebas cubren fallos inyectados, replay, identidades múltiples,
adaptadores de corpus, migración v0/v1 y v2, idempotencia, rechazo de esquemas
futuros y ausencia de tablas UPOS tras migrar.
