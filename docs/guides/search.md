# Búsqueda opcional de semordnilaps

`sp_search_ngrams` lee en modo sólo lectura generaciones finales de DuckDB y
busca `reverse(source_norm_key) == target_norm_key`.

```bash
uv run sp_search_ngrams \
  --db-path data/ngrams/counts.duckdb \
  --out data/search/es_gl.tsv \
  --src-lang es --tgt-lang gl \
  --src-corpus wikisource_20231201 \
  --tgt-corpus wikisource_20231201 \
  --min-src-count 5 --min-tgt-count 5
```

Cuando un alias contiene varias políticas, use los IDs mostrados por
`sp_ngrams db stats`:

```text
--src-dataset-id ID --tgt-dataset-id ID
```

También admite `--src-n`, `--tgt-n`, límites de longitud normalizada,
`--max-results`, palíndromos e idénticos. Para datos v2, `auto` y `compact`
leen la generación activa; `raw` falla porque staging se elimina tras una
finalización válida. La salida TSV se escribe de forma incremental.
