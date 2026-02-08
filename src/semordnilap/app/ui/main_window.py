from functools import partial
from pathlib import Path

import dearpygui.dearpygui as dpg

from semordnilap.app.logic.filtering import (
    filter_pairs_sources,
    filter_pairs_targets,
    filter_semordnilaps_sources,
    filter_semordnilaps_targets,
)
from semordnilap.app.logic.iteration import (
    build_source_target_pairs,
)
from semordnilap.app.logic.loader import load_semordnilaps, load_words_filter
from semordnilap.app.logic.persistence import append_word_if_missing
from semordnilap.app.logic.state import AppState, Ngram

SEMORDNILAPS_TAG = "semordnilaps_path"
SOURCE_WORDS_FILTER_TAG = "source_words_filter_path"
TARGET_WORDS_FILTER_TAG = "target_words_filter_path"
STATUS_TAG = "status"

HEADER_HEIGHT = 30
FOOTER_HEIGHT = 30


def _set_status(text, ok=True):
    dpg.set_value(STATUS_TAG, text)
    dpg.configure_item(
        STATUS_TAG, color=(120, 220, 120, 255) if ok else (220, 120, 120, 255)
    )


def _semordnilaps_selected(_, app_data):
    path = app_data["file_path_name"]

    try:
        json_data = load_semordnilaps(path)

        # Validate
        AppState.semordnilaps = json_data
        dpg.set_value(SEMORDNILAPS_TAG, path)
        _set_status(
            f"Semordnilaps JSON loaded successfully ({len(json_data)} entries)",
            ok=True,
        )

    except FileNotFoundError as e:
        AppState.semordnilaps = None
        dpg.set_value(SEMORDNILAPS_TAG, "No file selected")
        _set_status(f"Invalid file: {e}", ok=False)


def _source_words_filter_selected(_, app_data):
    _load_words_filter(app_data, "source")


def _target_words_filter_selected(_, app_data):
    _load_words_filter(app_data, "target")


def _load_words_filter(app_data, kind):
    path = app_data["file_path_name"]
    filepath = Path(path)

    try:
        if filepath.exists():
            words = load_words_filter(path)
            if kind == "source":
                AppState.source_words_filter = words
                AppState.source_words_filter_path = path
                dpg.set_value(SOURCE_WORDS_FILTER_TAG, path)
            elif kind == "target":
                AppState.target_words_filter = words
                AppState.target_words_filter_path = path
                dpg.set_value(TARGET_WORDS_FILTER_TAG, path)
            _set_status(
                f"{kind.capitalize()} words filter loaded ({len(words)})", True
            )
        else:
            dpg.set_value("_pending_filter_path", str(filepath))
            dpg.set_value("_pending_filter_kind", kind)
            dpg.show_item("confirm_create_modal")

    except Exception as e:
        AppState.words_filter = None
        _set_status(f"Error loading words filter: {e}", ok=False)


def _create_output_file():
    path = dpg.get_value("_pending_filter_path")
    kind = dpg.get_value("_pending_filter_kind")

    file_path = Path(path)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)
        words = load_words_filter(path)

        if kind == "source":
            AppState.source_words_filter = words
            dpg.set_value(SOURCE_WORDS_FILTER_TAG, str(file_path))

        elif kind == "target":
            AppState.target_words_filter = words
            dpg.set_value(TARGET_WORDS_FILTER_TAG, str(file_path))

        else:
            raise RuntimeError("Unknown filter kind")

        _set_status(
            f"{kind.capitalize()} output file created and loaded",
            ok=True,
        )

    except Exception as e:
        _set_status(f"Error creating file: {e}", ok=False)

    finally:
        dpg.hide_item("confirm_create_modal")
        dpg.set_value("_pending_output_path", "")
        dpg.set_value("_pending_filter_kind", "")


def _start_interactive():
    if AppState.semordnilaps is None:
        _set_status("Semordnilaps not loaded", ok=False)
        return

    if AppState.pairs is None:
        AppState.pairs = build_source_target_pairs(AppState.semordnilaps)
        _set_status(f"Loaded pairs ({len(AppState.pairs)} entries)", ok=True)

    dpg.show_item("interactive_group")
    dpg.show_item("continue_word_button")
    _advance_pair()


def _advance_pair():

    if not AppState.pairs:
        _set_status("Interactive filtering finished ✅", ok=True)
        dpg.hide_item("interactive_group")
        return

    current_pair = AppState.pairs[0]
    AppState.current_source_ngram.set(current_pair[0])
    AppState.current_target_ngram.set(current_pair[1])
    _update_interactive_buttons()


def _continue_pair():
    if AppState.pairs:
        AppState.pairs.pop(0)
        _advance_pair()
    else:
        _set_status("Interactive filtering finished ✅", ok=True)


def _filter_source_word(word: str):
    if AppState.source_words_filter_path is None:
        _set_status("Source words filter file not set", ok=False)
        return

    append_word_if_missing(
        filepath=AppState.source_words_filter_path,
        word=word,
        current_words=AppState.source_words_filter,
    )

    AppState.pairs = filter_pairs_sources(AppState.pairs, {word})

    _set_status(f'Added "{word}" to source filter', ok=True)
    _advance_pair()


def _filter_target_word(word: str):
    print(word)
    if AppState.target_words_filter_path is None:
        _set_status("Target words filter file not set", ok=False)
        return

    append_word_if_missing(
        filepath=AppState.target_words_filter_path,
        word=word,
        current_words=AppState.target_words_filter,
    )

    AppState.pairs = filter_pairs_targets(AppState.pairs, {word})

    _set_status(f'Added "{word}" to target filter', ok=True)
    _advance_pair()


def _draw_ngram_buttons(parent: str, ngram: Ngram, on_click: callable):
    dpg.delete_item(parent, children_only=True)

    ngram_phrase = ngram.get_ngram()
    tokens = ngram.get_tokens()
    n = max(len(tokens), 1)

    print(tokens)

    def _callback(sender, app_data, user_data):
        on_click(user_data)

    dpg.add_button(
        parent=parent,
        label=ngram_phrase,
        width=-1,
        height=32,
        user_data=ngram_phrase,
        callback=_callback,
    )

    if n >= 2:
        dpg.add_spacer(parent=parent, height=4)
        with dpg.table(
            parent=parent,
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
            width=-1,
        ):
            for _ in tokens:
                dpg.add_table_column(init_width_or_weight=1)

            with dpg.table_row():
                for token in tokens:
                    dpg.add_button(
                        label=token,
                        width=-1,
                        height=28,
                        user_data=token,
                        callback=_callback,
                    )


def _draw_source_target_table():
    dpg.delete_item("interactive_table", children_only=True)

    with dpg.table(
        parent="interactive_table",
        header_row=False,
        resizable=False,
        policy=dpg.mvTable_SizingStretchProp,
        width=-1,
    ):
        dpg.add_table_column(init_width_or_weight=1)
        dpg.add_table_column(init_width_or_weight=1)
        with dpg.table_row():
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=1)
                dpg.add_text("Source")
                dpg.add_spacer(width=1)

            with dpg.group(horizontal=True):
                dpg.add_spacer(width=1)
                dpg.add_text("Target")
                dpg.add_spacer(width=1)
        with dpg.table_row():
            with dpg.group():
                _draw_ngram_buttons(
                    parent=dpg.last_item(),
                    ngram=AppState.current_source_ngram,
                    on_click=_filter_source_word,
                )

            with dpg.group():
                _draw_ngram_buttons(
                    parent=dpg.last_item(),
                    ngram=AppState.current_target_ngram,
                    on_click=_filter_target_word,
                )


def _update_interactive_buttons():
    _draw_source_target_table()


def _run_filtering():
    if AppState.semordnilaps is None:
        _set_status("Semordnilaps not loaded", ok=False)
        return

    if AppState.source_words_filter is None:
        _set_status("Words filter not loaded", ok=False)
        return

    if AppState.target_words_filter is None:
        _set_status("Words filter not loaded", ok=False)
        return

    count_entries = len(AppState.semordnilaps)
    filtered = filter_semordnilaps_sources(
        AppState.semordnilaps, AppState.source_words_filter
    )
    AppState.semordnilaps = filtered

    _set_status(
        f"Filtering sources completed ({len(filtered)} entries)",
        ok=True,
    )

    filtered = filter_semordnilaps_targets(
        AppState.semordnilaps, AppState.target_words_filter
    )
    AppState.semordnilaps = filtered
    _set_status(
        f"Filtering targets completed ({len(filtered)} entries - {count_entries - len(filtered)} removed)",
        ok=True,
    )

    AppState.pairs = build_source_target_pairs(AppState.semordnilaps)


def _open_file_dialog(tag):
    dpg.show_item(tag)


def _export_pairs_to_file(path: str):
    if not AppState.pairs:
        _set_status("No pairs to export", ok=False)
        return
    pairs = sorted(AppState.pairs, key=lambda x: (x[0], x[1]))

    try:
        with open(path, "w", encoding="utf-8") as f:
            for source, target in pairs:
                f.write(f"{source} ↔ {target}\n")
        _set_status(f"Exported {len(pairs)} pairs to {path}", ok=True)
    except Exception as e:
        _set_status(f"Export failed: {e}", ok=False)


def _export_dialog_selected(_, app_data):
    directory = app_data["current_path"]
    filename = app_data["file_name"]

    if not filename:
        _set_status("Export cancelled", ok=False)
    path = str(Path(directory) / filename)
    _export_pairs_to_file(path)


def build_ui():
    with dpg.value_registry():
        dpg.add_string_value(tag="_pending_filter_path", default_value="")
        dpg.add_string_value(tag="_pending_filter_kind", default_value="")

    # ---- File dialogs ---- #
    with dpg.file_dialog(
        directory_selector=False,
        show=False,
        callback=_semordnilaps_selected,
        tag="semordnilaps_dialog",
        user_data=SEMORDNILAPS_TAG,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".json")

    with dpg.file_dialog(
        show=False,
        callback=_source_words_filter_selected,
        tag="source_filter_dialog",
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")

    with dpg.file_dialog(
        show=False,
        callback=_target_words_filter_selected,
        tag="target_filter_dialog",
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")

    with dpg.file_dialog(
        show=False,
        callback=_export_dialog_selected,
        tag="export_dialog",
        directory_selector=False,
        modal=True,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")

    with dpg.window(
        tag="main_window",
        label="Semordnilaps filtering engine",
        no_title_bar=True,
        no_resize=True,
        no_move=True,
    ):
        with dpg.child_window(
            tag="header",
            border=True,
            autosize_x=True,
            height=HEADER_HEIGHT,
            no_scrollbar=True,
        ):
            with dpg.group(horizontal=True):
                dpg.add_text("Status:", color=(180, 180, 180))
                dpg.add_text("", tag=STATUS_TAG)

        with dpg.child_window(
            tag="content_area",
            border=False,
            autosize_x=True,
            autosize_y=False,
            height=-HEADER_HEIGHT - FOOTER_HEIGHT,
        ):
            with dpg.collapsing_header(label="Files", default_open=True):
                with dpg.table(
                    header_row=False,
                    resizable=False,
                    policy=dpg.mvTable_SizingFixedFit,
                    borders_innerV=True,
                ):
                    dpg.add_table_column(
                        width_fixed=True, init_width_or_weight=220
                    )
                    dpg.add_table_column(width_stretch=True)
                    dpg.add_table_column(
                        width_fixed=True, init_width_or_weight=90
                    )

                    with dpg.table_row():
                        dpg.add_text("Semordnilaps file:")
                        dpg.add_input_text(
                            default_value="No file selected",
                            tag=SEMORDNILAPS_TAG,
                            readonly=True,
                            width=-1,
                        )
                        dpg.add_button(
                            label="Browse",
                            width=80,
                            callback=lambda: _open_file_dialog(
                                "semordnilaps_dialog"
                            ),
                        )

                    with dpg.table_row():
                        dpg.add_text("Source words filter:")
                        dpg.add_input_text(
                            default_value="No file selected",
                            tag=SOURCE_WORDS_FILTER_TAG,
                            readonly=True,
                            width=-1,
                        )
                        dpg.add_button(
                            label="Browse",
                            width=80,
                            callback=lambda: dpg.show_item(
                                "source_filter_dialog"
                            ),
                        )

                    with dpg.table_row():
                        dpg.add_text("Target words filter:")
                        dpg.add_input_text(
                            default_value="No file selected",
                            tag=TARGET_WORDS_FILTER_TAG,
                            readonly=True,
                            width=-1,
                        )
                        dpg.add_button(
                            label="Browse",
                            width=80,
                            callback=lambda: dpg.show_item(
                                "target_filter_dialog"
                            ),
                        )

            dpg.add_spacer(height=15)

            with dpg.group(
                horizontal=True,
                show=True,
            ):
                dpg.add_button(
                    label="Filter",
                    width=100,
                    callback=_run_filtering,
                )
                dpg.add_button(
                    label="Start",
                    width=100,
                    callback=_start_interactive,
                )
                dpg.add_button(
                    label="Export",
                    width=100,
                    callback=lambda: dpg.show_item("export_dialog"),
                )

            dpg.add_spacer(height=10)

            # --- INTERACTIVE BUTTONS ---
            with dpg.group(show=False, tag="interactive_group"):
                with dpg.child_window(
                    tag="interactive_table",
                    border=False,
                    autosize_x=True,
                    height=140,
                    no_scrollbar=True,
                ):
                    pass

            dpg.add_spacer(height=5)

            dpg.add_button(
                label="Skip / Continue",
                tag="continue_word_button",
                width=300,
                callback=_continue_pair,
                show=False,
            )
        with dpg.child_window(
            tag="footer",
            border=False,
            autosize_x=True,
            height=FOOTER_HEIGHT,
            no_scrollbar=True,
        ):
            with dpg.table(
                header_row=False,
                borders_innerV=False,
                resizable=False,
                width=-1,
                policy=dpg.mvTable_SizingStretchProp,
            ):
                dpg.add_table_column(init_width_or_weight=1)
                dpg.add_table_column(
                    init_width_or_weight=0.3
                )  # Don't know why this works
                dpg.add_table_column(init_width_or_weight=1)

                with dpg.table_row():
                    dpg.add_text(" ")
                    dpg.add_text("Made with love ❤️", color=(180, 180, 180))
                    dpg.add_text(" ")
    dpg.set_primary_window("main_window", True)
    with dpg.window(
        label="Confirm file creation",
        modal=True,
        show=False,
        tag="confirm_create_modal",
        no_title_bar=False,
        width=400,
        height=120,
    ):
        dpg.add_text("The file does not exist.\nDo you want to create it?")
        dpg.add_spacer(height=10)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Yes", callback=_create_output_file)
            dpg.add_button(
                label="No",
                callback=lambda: dpg.hide_item("confirm_create_modal"),
            )
