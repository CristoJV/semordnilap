# N-gramas y DuckDB

## Contrato textual

`sp_ngrams` extrae directamente texto fuente. No necesita Stanza, no crea un
dataset etiquetado y no acepta `ud-jsonl`. Cada fila lógica contiene:

- `lang`, `corpus`, `text`, `n` y `count`;
- `norm_key`, usado para la búsqueda normalizada;
- `has_punctuation`, calculado a partir de la superficie almacenada.

`--punctuation keep` es el valor por defecto: conserva la puntuación en la
superficie textual y permite que las ventanas léxicas la crucen, pero los
signos no cuentan para `n` ni forman parte de `norm_key`. Los documentos nunca
se cruzan. `--punctuation boundary` trata cada signo como un límite duro. Las
grafías antiguas `--omit-punctuation`, `--keep-punctuation` y
`--no-omit-punctuation` se aceptan por compatibilidad, pero ya no aparecen en
la interfaz documentada.

## Identidad e idempotencia

La identidad de un dataset deriva de
`source artifact_id + extraction policy hash + lang + corpus`. La política
incluye normalización, superficie, límites, puntuación, `limit_docs` y, para
fuentes gestionadas, el adaptador seleccionado. `lang/corpus` es un alias
legible; si corresponde a varias identidades hay que indicar `--dataset-id`.

La extracción mantiene como máximo el contador configurado con
`--flush-unique-ngrams`. Cada segmento se confirma junto con su ledger y el
cursor en una transacción. Repetir un segmento idéntico es un no-op; reutilizar
su ID con otro digest falla.

Al terminar de leer el corpus, `extract` siempre finaliza la generación. La
finalización consolida primero por tamaño `n` y por particiones hash; cada
parte tiene su propia transacción y checkpoint. Solo cuando todas terminan se
activa la generación de forma atómica y se elimina el staging. Por eso un
lector nunca ve una generación parcial y un reintento no repite las partes ya
confirmadas. Las opciones históricas `--chunk-docs` y
`--no-compact-after-count` ya no se muestran: la primera no gobernaba los
checkpoints y la segunda no podía omitir la finalización moderna.

Para diagnosticar y recuperar una interrupción sin volver a leer la fuente:

```bash
uv run sp_ngrams db stats --db-path data/ngrams/counts.duckdb \
  --lang gl --corpus corpusnos

uv run sp_ngrams db finalize --db-path data/ngrams/counts.duckdb \
  --lang gl --corpus corpusnos
```

`db stats` muestra `completed_documents`, los chunks confirmados y el progreso
de las partes de finalización. También se puede repetir exactamente el comando
`extract`: saltará los documentos ya confirmados y retomará la finalización.

## Adaptadores de corpus fuente

`--adapter auto` reconoce manifiestos gestionados. También se puede fijar el
adaptador para dejar la operación reproducible:

```bash
uv run sp_ngrams extract --adapter wikisource \
  --input data/corpus/wikisource --lang es \
  --db-path data/ngrams/counts.duckdb

uv run sp_ngrams extract --adapter corpusnos \
  --input data/corpus/corpusnos --lang gl \
  --db-path data/ngrams/counts.duckdb

uv run sp_ngrams extract --adapter corpusnos \
  --input data/corpus/corpusnos/corpusnos_dta_books --lang gl \
  --db-path data/ngrams/counts.duckdb
```

Wikisource deriva un alias como `wikisource_20231201`; CorpusNÓS usa
`corpusnos` para la colección o `corpusnos_<config>` para un artefacto.
`--corpus NOMBRE` los sustituye. Para entradas no gestionadas use
`--adapter raw` junto con `--format txt|jsonl` y `--text-field`.

## Esquema DuckDB v3 y migración

Las bases nuevas usan el esquema 3. Las tablas de generaciones conservan sus
nombres `ngram_stage_v2` y `ngram_final_v2` para no reescribir datos textuales
existentes; el número de versión describe el contrato completo de la base, no
el sufijo histórico de esas tablas.

Una base anterior no se modifica al abrirla. La migración debe solicitarse:

```bash
uv run sp_ngrams db migrate --db-path data/ngrams/counts.duckdb
```

La migración es transaccional e idempotente:

- v0/v1 conserva los recuentos y añade `has_punctuation=false`;
- v2 conserva recuentos, generaciones y ledgers textuales;
- elimina `ngram_upos_counts`, `ngram_upos_totals`,
  `ngram_upos_stage_v2` y `ngram_upos_final_v2`;
- rechaza una versión futura que el programa no conozca.

La eliminación de las cuatro tablas UPOS es intencionada. Conviene hacer una
copia de la base antes de migrar si esos datos gramaticales deben conservarse
fuera de Semordnilap.

## Exportación y mantenimiento

El TSV actual tiene versión 2 y columnas `lang`, `corpus`, `text`, `n`,
`count`, `score`, `norm_key` y `has_punctuation`.

```bash
uv run sp_ngrams db stats --db-path DB --lang es --corpus wiki --verbose

uv run sp_ngrams export --db-path DB --lang es --corpus wiki \
  --dataset-id DATASET_ID --out es.tsv --min-count 5

uv run sp_ngrams db delete --db-path DB --lang es --corpus wiki

uv run sp_ngrams db finalize --db-path DB --lang es --corpus wiki
```

`db stats` funciona también como inventario: muestra todas las tablas físicas
y su función, los aliases `lang/corpus` disponibles, almacenamiento legacy o
por generaciones, estado de cada dataset y recuentos por `n`. Aunque un filtro
no encuentre datos, conserva el catálogo global y propone usar uno de sus
aliases exactos. `--verbose` añade las filas raw más frecuentes y todas las
identidades de generación.

`db compact` actúa únicamente sobre las tablas legacy `ngram_counts` y
`ngram_totals`; no es parte de una extracción moderna. La exportación usa un
archivo parcial, checksum y promoción atómica. Las tablas legacy siguen
disponibles para bases migradas y para operaciones directas de compatibilidad.
