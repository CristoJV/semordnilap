# Pipeline completo: corpus, UPOS y n-gramas

## 1. Instalar

```bash
uv sync
```

## 2. Descargar Wikisource

```bash
uv run sp_corpus_wikisource \
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
uv run sp_corpus_wikisource ... --resume
```

`--force` reemplaza únicamente el artefacto solicitado. No se escribe nunca un
archivo final incompleto.

## 3. Descargar y comprobar Stanza

```bash
uv run sp_tag download \
  --langs es gl \
  --model-dir data/models/stanza

uv run sp_tag smoke \
  --langs es gl \
  --model-dir data/models/stanza
```

El smoke test carga modelos reales, anota una frase por idioma e imprime el
digest exacto de cada conjunto de modelos.

## 4. Etiquetar

```bash
uv run sp_tag annotate \
  --input data/corpus/wikisource/wikisource_es_20231201 \
  --format jsonl \
  --text-field text \
  --id-field id \
  --lang es \
  --model-dir data/models/stanza \
  --out data/tagged/wikisource_es_20231201
```

Repítase con `gl`. Una ejecución nueva usa `ud-jsonl-v2`: directorio con
shards `.ud.jsonl.gz`, offsets absolutos, UPOS, rasgos UD, ordinales y
checksums. El perfil `compact` es el predeterminado; `--profile full` añade
lema y XPOS.

La barra muestra documentos, tokens, shards y cuarentenas. Durante una llamada
larga a Stanza se emite un heartbeat cada 30 segundos; se cambia con
`--heartbeat-seconds`.

### Documentos largos y errores

Por defecto, documentos mayores de 250 000 caracteres se dividen de forma
determinista en límites de párrafo, frase o espacio. Los resultados recuperan
offsets globales y el manifiesto conserva los límites. Un tramo sin ningún
límite seguro se cuarentena junto al motivo y el pipeline continúa. Opciones:

```text
--max-document-chars N
--on-document-error quarantine|fail
--shard-docs N
```

### Reanudar

```bash
uv run sp_tag annotate <los mismos argumentos> --resume
```

V2 sólo reabre el último cursor confirmado y nunca deserializa shards ya
finalizados. Si existe una parcial v1 de una ejecución anterior, `auto` la
detecta y usa el protocolo v1: checkpoint de offsets y, una única vez para
checkpoints antiguos, indexación visible de la parcial. Puede fijarse
`--output-format ud-jsonl-v1` expresamente. No use `--force` para un resume.

## 5. Extraer n-gramas

```bash
uv run sp_ngrams extract \
  --input data/tagged/wikisource_es_20231201 \
  --format auto \
  --lang es \
  --corpus wikisource_20231201 \
  --max-n 3 \
  --flush-unique-ngrams 250000 \
  --db-path data/ngrams/counts.duckdb
```

`auto` reconoce el esquema UD; por tanto no puede perder UPOS mediante una
retokenización silenciosa. La puntuación se conserva por defecto: aparecen
superficies como `niña, el` y `camino. Antes`, incluso al cruzar frases. Nunca
se cruza un límite de documento. `--omit-punctuation` sólo existe como modo de
compatibilidad.

Cada segmento se confirma con recuentos, distribución UPOS y checkpoint en
una transacción. Repetir el comando es un no-op si la identidad ya está
completa; una política o fuente distinta produce otro `dataset_id`. Un
`--limit-docs` produce una identidad de muestra separada.

## 6. Inspeccionar y exportar

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
