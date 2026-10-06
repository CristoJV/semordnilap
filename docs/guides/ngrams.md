# N-gramas y DuckDB

## Contrato textual

`sp_ngrams` extrae directamente texto fuente. No necesita Stanza, no crea un
dataset etiquetado y no acepta `ud-jsonl`. Cada fila lógica contiene:

- `lang`, `corpus`, `text`, `n` y `count`;
- `norm_key`, usado para la búsqueda normalizada;
- `has_punctuation`, calculado a partir de la superficie almacenada.

La puntuación y los saltos de frase se pueden cruzar por defecto, pero nunca
se cruzan documentos. No se conserva un campo independiente de cruce de frase.
`--omit-punctuation` mantiene el modo compatible que trata la puntuación como
límite.

## Identidad e idempotencia

La identidad de un dataset deriva de
`source artifact_id + extraction policy hash + lang + corpus`. La política
incluye normalización, superficie, límites, puntuación, `limit_docs` y, para
fuentes gestionadas, el adaptador seleccionado. `lang/corpus` es un alias
legible; si corresponde a varias identidades hay que indicar `--dataset-id`.

La extracción mantiene como máximo el contador configurado con
`--flush-unique-ngrams`. Cada segmento se confirma junto con su ledger y el
cursor en una transacción. Repetir un segmento idéntico es un no-op; reutilizar
su ID con otro digest falla. La finalización agrega y activa una generación
textual de forma atómica.

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
```

`db stats` funciona también como inventario: muestra todas las tablas físicas
y su función, los aliases `lang/corpus` disponibles, almacenamiento legacy o
por generaciones, estado de cada dataset y recuentos por `n`. Aunque un filtro
no encuentre datos, conserva el catálogo global y propone usar uno de sus
aliases exactos. `--verbose` añade las filas raw más frecuentes y todas las
identidades de generación.

La exportación usa un archivo parcial, checksum y promoción atómica. Las
tablas legacy `ngram_counts` y `ngram_totals` siguen disponibles para bases
migradas y para las operaciones directas de compatibilidad.
