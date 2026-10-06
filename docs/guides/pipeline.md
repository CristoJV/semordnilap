# Pipeline completo: corpus y n-gramas

## 1. Instalar

```bash
uv sync
```

## 2. Descargar un corpus

La orden `sp_corpus` selecciona la fuente mediante un subcomando.

### Wikisource

```bash
uv run sp_corpus wikisource \
  --langs es gl \
  --date 20231201 \
  --revision <REVISION_HF> \
  --out-dir data/corpus/wikisource
```

Se crean dos directorios, `wikisource_es_20231201/` y
`wikisource_gl_20231201/`, con shards JSONL gzip y `manifest.json`. El
manifiesto contiene revisión, configuración, documentos rechazados, checksums
y `artifact_id`. La descarga es streaming y reanudable:

```bash
uv run sp_corpus wikisource ... --resume
```

`--force` reemplaza únicamente el artefacto solicitado. No se escribe nunca un
archivo final incompleto.

### CorpusNÓS

La selección predeterminada evita las fuentes con más ruido (`web_crawls` y
`translation_corpora`) y descarga libros, artículos de investigación,
prensa/blogs y contenido enciclopédico:

```bash
uv run sp_corpus corpusnos \
  --revision <REVISION_HF> \
  --out-dir data/corpus/corpusnos
```

Puede elegirse una o varias categorías lógicas:

```bash
uv run sp_corpus corpusnos \
  --subsets books research_articles encyclopedic \
  --out-dir data/corpus/corpusnos
```

`--subsets all` incluye las ocho categorías. Para controlar por separado los
datos públicos y los cedidos por acuerdo, `--configs` acepta los nombres
exactos de Hugging Face; por ejemplo:

```bash
uv run sp_corpus corpusnos \
  --configs public_data_encyclopedic dta_encyclopedic \
  --out-dir data/corpus/corpusnos
```

Cada configuración produce un directorio `corpusnos_<config>/`. La descarga
es streaming, comprimida y dividida en shards; `--resume` conserva artefactos
ya completos y continúa los parciales.

## 3. Extraer directamente desde el corpus

Ésta es la ruta recomendada cuando sólo se necesitan frecuencias y superficies
textuales. No ejecuta Stanza ni crea un corpus etiquetado intermedio.

Wikisource selecciona dentro de la colección exactamente el artefacto cuyo
idioma coincide con `--lang`:

```bash
uv run sp_ngrams extract \
  --adapter wikisource \
  --input data/corpus/wikisource \
  --lang es \
  --max-n 3 \
  --flush-unique-ngrams 250000 \
  --db-path data/ngrams/counts.duckdb
```

CorpusNÓS sólo admite `--lang gl`. Una colección completa procesa exactamente
las configuraciones enumeradas en su manifest:

```bash
uv run sp_ngrams extract \
  --adapter corpusnos \
  --input data/corpus/corpusnos \
  --lang gl \
  --max-n 3 \
  --flush-unique-ngrams 250000 \
  --db-path data/ngrams/counts.duckdb
```

También puede procesarse una sola configuración:

```bash
uv run sp_ngrams extract \
  --adapter corpusnos \
  --input data/corpus/corpusnos/corpusnos_dta_books \
  --lang gl \
  --db-path data/ngrams/counts.duckdb
```

`--adapter auto` es el valor predeterminado y reconoce los manifests, pero
fijarlo expresamente deja más clara la operación. Los aliases predeterminados
son `wikisource_<fecha>`, `corpusnos` para una colección y
`corpusnos_<config>` para un único artefacto; `--corpus` puede sustituirlos.

La puntuación se conserva, se registra `has_punctuation` y nunca se cruzan
documentos. No se persisten UPOS ni un indicador de cruce de frase. La
extracción sigue siendo transaccional, reanudable e idempotente en DuckDB.
Los artefactos `ud-jsonl` producidos por la utilidad independiente `sp_tag` no
son entradas aceptadas por `sp_ngrams`.

## 4. Inspeccionar, migrar y exportar

Las bases nuevas usan el esquema textual v3. Para una base anterior ejecute
una migración explícita; conserva recuentos textuales y elimina las tablas UPOS:

```bash
uv run sp_ngrams db migrate \
  --db-path data/ngrams/counts.duckdb
```

```bash
uv run sp_ngrams db stats \
  --db-path data/ngrams/counts.duckdb \
  --lang es \
  --corpus wikisource_20231201

uv run sp_ngrams export \
  --db-path data/ngrams/counts.duckdb \
  --lang es \
  --corpus wikisource_20231201 \
  --out data/ngrams/es.tsv \
  --min-count 5
```

Si el alias tiene varias políticas, copie de `db stats` el `dataset_id` y
añada `--dataset-id ...`. La exportación usa `.part`, `fsync`, promoción
atómica y manifiesto con checksum.

## Verificación y benchmarks

```bash
uv run pytest -q
uv run ruff check .
uv run python scripts/benchmark_core.py \
  --windows 10000 1000000 \
  --oversized-document
```

El benchmark informa throughput y pico RSS; son medidas de la máquina actual,
no umbrales universales.
