"""Gradio interface for exploring semordnilap search results."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from semordnilap.review.application import (
    build_detail_markdown,
    filter_rows,
    rows_to_table,
)
from semordnilap.review.application.services import TABLE_HEADERS
from semordnilap.review.domain import ReviewFilters, ReviewRow
from semordnilap.review.infrastructure import TsvReviewRepository


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def resolve_uploaded_path(file_value) -> str:
    if file_value is None:
        return ""
    if isinstance(file_value, str):
        return file_value
    if isinstance(file_value, dict):
        return file_value.get("path") or file_value.get("name") or ""
    return str(getattr(file_value, "name", "") or "")


def parse_n_filter(value: str) -> int | None:
    return None if value == "all" else int(value)


def load_rows(path_value: str) -> tuple[list[ReviewRow], str]:
    if not path_value or not path_value.strip():
        return [], "Select or enter a TSV file."

    path = Path(path_value).expanduser()
    if not path.exists():
        return [], f"File not found: {path}"
    if not path.is_file():
        return [], f"Not a file: {path}"

    rows = TsvReviewRepository().load(path)
    rows.sort(key=lambda row: -row.pair_score)
    return rows, f"Loaded {len(rows)} pairs from {path}"


def apply_filters(
    rows: list[ReviewRow],
    source_contains: str,
    target_contains: str,
    min_pair_score: float,
    min_source_count: int,
    min_target_count: int,
    source_n: str,
    target_n: str,
    limit: int,
) -> tuple[list[list], str, list[ReviewRow]]:
    filters = ReviewFilters(
        source_contains=source_contains,
        target_contains=target_contains,
        min_pair_score=min_pair_score,
        min_source_count=min_source_count,
        min_target_count=min_target_count,
        source_n=parse_n_filter(source_n),
        target_n=parse_n_filter(target_n),
        limit=limit,
    )
    filtered = filter_rows(rows, filters)
    return (
        rows_to_table(filtered),
        build_detail_markdown(filtered[0] if filtered else None),
        filtered,
    )


def build_interface(initial_path: Path | None):
    import gradio as gr

    initial_rows, initial_status = ([], "No TSV loaded.")
    if initial_path is not None:
        initial_rows, initial_status = load_rows(str(initial_path))

    initial_table_rows = rows_to_table(initial_rows[:500])
    initial_detail = build_detail_markdown(
        initial_rows[0] if initial_rows else None
    )

    with gr.Blocks(title="Semordnilap Review") as interface:
        gr.Markdown("# Semordnilap Review")

        rows_state = gr.State(initial_rows)
        filtered_state = gr.State(initial_rows[:500])

        with gr.Row():
            path_input = gr.Textbox(
                label="TSV path",
                value=str(initial_path) if initial_path else "",
                scale=4,
            )
            load_button = gr.Button("Load", variant="primary")

        file_input = gr.File(
            label="Select TSV",
            file_types=[".tsv", ".txt"],
            type="filepath",
        )
        status = gr.Markdown(initial_status)

        with gr.Row():
            source_contains = gr.Textbox(label="Source contains")
            target_contains = gr.Textbox(label="Target contains")
            min_pair_score = gr.Number(label="Min score", value=0.0)
            min_source_count = gr.Number(label="Min source count", value=0)
            min_target_count = gr.Number(label="Min target count", value=0)

        with gr.Row():
            source_n = gr.Dropdown(
                ["all", "1", "2", "3"], value="all", label="Source n"
            )
            target_n = gr.Dropdown(
                ["all", "1", "2", "3"], value="all", label="Target n"
            )
            limit = gr.Number(label="Rows", value=500, precision=0)
            apply_button = gr.Button("Apply filters")

        table = gr.Dataframe(
            headers=TABLE_HEADERS,
            value=initial_table_rows,
            datatype=[
                "str",
                "str",
                "number",
                "number",
                "number",
                "number",
                "number",
                "str",
                "str",
            ],
            interactive=False,
            wrap=True,
            label="Pairs",
        )
        detail = gr.Markdown(initial_detail)

        def load_path(path_value):
            rows, message = load_rows(path_value)
            table_rows, detail_value, filtered = apply_filters(
                rows, "", "", 0.0, 0, 0, "all", "all", 500
            )
            return rows, filtered, table_rows, detail_value, message

        def on_file_selected(file_value):
            path_value = resolve_uploaded_path(file_value)
            rows, filtered, table_rows, detail_value, message = load_path(
                path_value
            )
            return (
                path_value,
                rows,
                filtered,
                table_rows,
                detail_value,
                message,
            )

        def on_filter(
            rows,
            source_query,
            target_query,
            score,
            source_count,
            target_count,
            source_n_value,
            target_n_value,
            limit_value,
        ):
            return apply_filters(
                rows,
                source_query,
                target_query,
                float(score or 0),
                int(source_count or 0),
                int(target_count or 0),
                source_n_value,
                target_n_value,
                int(limit_value or 500),
            )

        def on_select(filtered_rows):
            return build_detail_markdown(filtered_rows[0] if filtered_rows else None)

        def on_row_select(filtered_rows, evt: gr.SelectData | None = None):
            if evt is None:
                return build_detail_markdown(
                    filtered_rows[0] if filtered_rows else None
                )
            row_index = (
                evt.index[0] if isinstance(evt.index, tuple) else evt.index
            )
            if row_index is None or row_index >= len(filtered_rows):
                return build_detail_markdown(None)
            return build_detail_markdown(filtered_rows[row_index])

        load_button.click(
            load_path,
            inputs=[path_input],
            outputs=[rows_state, filtered_state, table, detail, status],
        )
        file_input.change(
            on_file_selected,
            inputs=[file_input],
            outputs=[
                path_input,
                rows_state,
                filtered_state,
                table,
                detail,
                status,
            ],
        )
        apply_button.click(
            on_filter,
            inputs=[
                rows_state,
                source_contains,
                target_contains,
                min_pair_score,
                min_source_count,
                min_target_count,
                source_n,
                target_n,
                limit,
            ],
            outputs=[table, detail, filtered_state],
        )
        table.select(on_row_select, inputs=[filtered_state], outputs=[detail])
        filtered_state.change(on_select, inputs=[filtered_state], outputs=[detail])

    return interface


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Review semordnilap search results")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)

    logger.info("Starting review app")
    if args.input:
        logger.info("Initial TSV: %s", args.input)

    interface = build_interface(args.input)
    interface.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
