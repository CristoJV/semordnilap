# N-gramas y DuckDB

## Identidad e idempotencia

La clave real de un dataset es
`source artifact_id + extraction policy hash + lang + corpus`. La política
incluye normalización, superficie, límites, puntuación, `limit_docs` y, para
fuentes gestionadas, el adaptador seleccionado.
`lang/corpus` es sólo un alias legible.

## Adaptadores de corpus fuente

`extract` procesa directamente los shards descargados, sin Stanza ni un
dataset etiquetado intermedio. `--lang` sigue siendo obligatorio para que la
política lingüística sea explícita. `--adapter auto` es el valor por defecto,
pero puede fijarse el adaptador en operaciones reproducibles:

```bash
# el manifest de colección selecciona sólo el artefacto español
uv run sp_ngrams extract --adapter wikisource \
  --input data/corpus/wikisource --lang es \
  --db-path data/ngrams/counts.duckdb

# procesa la colección completa de configuraciones descargadas
uv run sp_ngrams extract --adapter corpusnos \
  --input data/corpus/corpusnos --lang gl \
  --db-path data/ngrams/counts.duckdb

# procesa una única configuración CorpusNÓS
uv run sp_ngrams extract --adapter corpusnos \
  --input data/corpus/corpusnos/corpusnos_dta_books --lang gl \
  --db-path data/ngrams/counts.duckdb
```

Wikisource deriva por defecto un alias como `wikisource_20231201`; un
artefacto CorpusNÓS individual usa `corpusnos_<config>` y la colección usa
`corpusnos`. `--corpus NOMBRE` permite sustituirlos. El adaptador raw genérico
permanece disponible con `--adapter raw` y las opciones `--format` y
`--text-field` existentes.

La ruta directa genera recuentos textuales, pero no UPOS:
`upos_counts` queda vacío y `cross_sentence_count` vale cero. Use una entrada
`ud-jsonl` etiquetada sólo cuando necesite esa evidencia contextual.

La extracción genera ventanas mediante iteradores y mantiene como máximo el
buffer configurado con `--flush-unique-ngrams`, incluso dentro de un único
documento grande. Cada flush recibe un `chunk_id` y digest deterministas. En
una transacción se escriben:

- recuentos textuales de staging;
- patrones UPOS y si cruzan frase;
- ledger del chunk;
- métricas y cursor del run.

Reproducir un chunk idéntico no cambia ningún total; el mismo ID con otro
digest falla.

## Generaciones finales

Al finalizar, DuckDB agrega una generación nueva, valida que el total textual
y el total UPOS coincidan, activa la generación y retira staging dentro de una
transacción. Los lectores nunca consumen una generación incompleta.

Las tablas antiguas `ngram_counts`/`ngram_totals` se conservan sólo para leer y
migrar bases existentes. Una base legacy se migra explícitamente:

```bash
uv run sp_ngrams db migrate --db-path data/ngrams/counts.duckdb
```

`db stats` siempre abre en sólo lectura y no ejecuta migraciones.

## Superficie y normalización

- Puntuación y saltos de frase se cruzan por defecto.
- `surface_display` conserva una grafía de origen con espacios normalizados.
- `surface_key` usa NFC, case-folding Unicode y espacios colapsados.
- `norm_key` elimina puntuación y acentos para la inversión.
- `ñ` permanece distinta; `--fold-nasal-letters` activa `ñ -> n`.
- Una misma superficie tiene un total único y una distribución separada de
  patrones, por ejemplo `{"ADP DET":73,"VERB DET":4}`.

## Operaciones

```bash
# inspección
uv run sp_ngrams db stats --db-path DB --lang es --corpus wiki --verbose

# exportación atómica
uv run sp_ngrams export --db-path DB --lang es --corpus wiki \
  --dataset-id DATASET_ID --out es.tsv --min-count 5

# borrado transaccional del alias completo
uv run sp_ngrams db delete --db-path DB --lang es --corpus wiki
```

`--export-source raw` no es válido para una generación v2 finalizada porque
su staging ya fue retirado. `compact` exige una generación completa. Si hay
varios `dataset_id` bajo el mismo alias, export y búsqueda fallan hasta que se
seleccione uno explícitamente.
