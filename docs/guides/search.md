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
`--max-results`, palíndromos e idénticos. Lee exclusivamente la generación
activa; el staging nunca es una fuente de búsqueda. La salida TSV se escribe
de forma incremental.

## Identidad y combinación de TSV

Cada fila contiene dos identificadores SHA-256 versionados:

- `pair_id` incluye idioma, corpus, superficie y tamaño de ambos lados;
- `lexical_pair_id` contiene la misma identidad sin los corpus y permite
  agrupar el mismo par encontrado en fuentes diferentes.

La superficie de identidad usa NFC, espacios canónicos y `casefold`: ignora
mayúsculas, pero conserva acentos, puntuación y límites entre palabras. El TSV
mantiene además la grafía mostrada en `source_text` y `target_text`.

Los recuentos, puntuación y `dataset_id` no intervienen en los IDs. Por ello,
una extracción nueva del mismo alias de corpus conserva los IDs comparables,
aunque cambien las muestras o frecuencias. `source_dataset_id` y
`target_dataset_id` registran la extracción exacta.

Se pueden ejecutar manualmente distintas combinaciones de corpus y concatenar
los TSV conservando una sola cabecera. Filtre o elimine duplicados exactos por
`pair_id`; agrupe evidencia equivalente entre corpus por `lexical_pair_id`.

```bash
uv run sp_concat_pairs \
  --out data/search/es_gl_all.tsv \
  data/search/es_wikisource-gl_wikisource.tsv \
  data/search/es_wikisource-gl_corpusnos.tsv
```

El concatenador no deduplica ni agrega frecuencias: valida que todos los TSV
tengan el mismo esquema y copia sus filas. Los IDs permiten decidir después si
se desea deduplicar por combinación de corpus o agrupar por pareja léxica.
