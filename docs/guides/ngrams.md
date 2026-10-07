# N-gramas y DuckDB

## Contrato textual y valores por defecto

`sp_ngrams` extrae texto fuente directamente. No necesita Stanza, no crea un
dataset etiquetado y no acepta `ud-jsonl`. Cada fila final contiene la
superficie textual, `n`, el recuento, `norm_key` y `has_punctuation`.

La extracción intenta conservar todo lo que pueda resultar útil. Por defecto:

| Política | Valor | Consecuencia |
|---|---:|---|
| `--max-n` | `3` | Cuenta unigramas, bigramas y trigramas. |
| `--filter-min-token-len` | `2` | Filtra tokens más cortos, salvo letras permitidas por idioma. |
| `--filter-max-token-len` | `30` | Filtra tokens más largos. |
| `--filter-min-norm-len` | `2` | Filtra claves normalizadas más cortas. |
| Stopwords | conservar | Incluye n-gramas formados solo por stopwords. |
| Puntuación | conservar y cruzar | Los signos quedan en la superficie, pero no cuentan para `n`. |
| Letras nasales | `ñ → n` | La clave normalizada agrupa ambas grafías. |

Los filtros que descartan datos llevan el prefijo `--filter-`:

- `--filter-all-stopword-ngrams` descarta ventanas formadas exclusivamente
  por stopwords;
- `--filter-punctuation-boundaries` hace de cada signo un límite duro;
- los tres filtros de longitud ajustan sus límites respectivos.

`--preserve-nasal-letters` no filtra filas: cambia la normalización para
conservar `ñ` en `norm_key`. Los documentos nunca se cruzan.

## Extracción y recuperación

```bash
uv run sp_ngrams extract --adapter corpusnos \
  --input data/corpus/corpusnos --lang gl \
  --db-path data/ngrams/counts.duckdb
```

La identidad de un dataset deriva de
`source artifact_id + extraction policy hash + lang + corpus`. Cualquier
opción que cambie el resultado crea otra identidad. Si un alias `lang/corpus`
corresponde a varias identidades, los lectores exigen `--dataset-id`.

`--flush-unique-ngrams` limita el número de claves distintas mantenidas en
memoria. Al alcanzarlo, el contador parcial se confirma en staging junto con
un ledger y un checkpoint documental. Un flush no elimina n-gramas: mueve
recuentos de memoria a DuckDB, y la finalización los vuelve a sumar.

Después del último documento, `extract` finaliza siempre la generación. La
agregación se divide por tamaño `n` y por ocho buckets hash; cada parte tiene
su propia transacción y checkpoint. Solo al terminar todas las partes se
activa la generación atómicamente. Un lector nunca ve totales parciales.

Para inspeccionar o reanudar sin volver a leer el corpus:

```bash
uv run sp_ngrams db stats --db-path data/ngrams/counts.duckdb \
  --lang gl --corpus corpusnos

uv run sp_ngrams db finalize --db-path data/ngrams/counts.duckdb \
  --lang gl --corpus corpusnos
```

También se puede repetir exactamente `extract`: salta los documentos y partes
ya confirmados. `--reset` es para reconstruir deliberadamente el dataset, no
para recuperar una interrupción.

## Adaptadores de corpus

`--adapter auto` reconoce manifiestos gestionados. `wikisource` y `corpusnos`
validan el manifiesto, el idioma, los artefactos declarados y el orden de los
shards. Para entradas genéricas use `--adapter raw`, `--format txt|jsonl` y,
si corresponde, `--text-field`.

Wikisource deriva un alias como `wikisource_20231201`; CorpusNÓS usa
`corpusnos` para la colección o `corpusnos_<config>` para un artefacto.
`--corpus NOMBRE` sustituye el alias inferido.

## Esquema DuckDB v4

El esquema actual solo admite almacenamiento por generaciones:

- `extraction_datasets`, `extraction_runs` y `extraction_chunks` registran
  identidad y progreso;
- `ngram_stage_v2` conserva los recuentos parciales recuperables;
- `ngram_finalization_parts` registra las partes consolidadas;
- `ngram_final_v2` contiene generaciones finales.

Los sufijos físicos `_v2` se conservan para evitar reescribir las tablas
modernas existentes; la versión del contrato global es 4. Ya no existen las
tablas ni los comandos de compactación del modelo anterior.

Solo se admite la migración explícita de v3 a v4:

```bash
uv run sp_ngrams db migrate --db-path data/ngrams/counts.duckdb
```

La migración es transaccional: preserva datasets, chunks, staging,
finalizaciones interrumpidas y generaciones finales, y elimina
`ngram_counts`, `ngram_totals` y `ngram_compactions`. Las bases v0–v2 deben
reextraerse o convertirse externamente antes de usar esta versión.

## Exportación y mantenimiento

```bash
uv run sp_ngrams export --db-path DB --lang es --corpus wiki \
  --dataset-id DATASET_ID --out es.tsv --min-count 5

uv run sp_ngrams db stats --db-path DB --lang es --corpus wiki --verbose
uv run sp_ngrams db delete --db-path DB --lang es --corpus wiki
```

La exportación lee exclusivamente `active_generation` y puede filtrar por
frecuencia, `n` y longitud de `norm_key` sin modificar el dataset almacenado.
Escribe un archivo parcial, calcula su checksum y lo promociona de forma
atómica. El TSV tiene las columnas `lang`, `corpus`, `text`, `n`, `count`,
`score`, `norm_key` y `has_punctuation`.
