# N-gramas y DuckDB

## Identidad e idempotencia

La clave real de un dataset es
`source artifact_id + extraction policy hash + lang + corpus`. La política
incluye normalización, superficie, límites, puntuación y `limit_docs`.
`lang/corpus` es sólo un alias legible.

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
