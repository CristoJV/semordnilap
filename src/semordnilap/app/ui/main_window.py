from pathlib import Path

import dearpygui.dearpygui as dpg

from semordnilap.app.logic.loader import load_semordnilaps
from semordnilap.app.logic.persistence import append_word_if_missing
from semordnilap.app.viewmodel.semordnilap_vm import (
    Axis,
    Ngram,
    SemordnilapViewModel,
)

SEMORDNILAPS_TAG = "semordnilaps_path"
PENDING_FILTER_TAG = "_pending_filter_path"
PENDING_FILTER_KIND_TAG = "_pending_filter_axis"
SOURCE_WORDS_FILTER_TAG = "source_words_filter_path"
TARGET_WORDS_FILTER_TAG = "target_words_filter_path"
STATUS_TAG = "status"
LOADING_OVERLAY_TAG = "loading_overlay"
SEMORDNILAPS_DIALOG_TAG = "semordnilaps_dialog"
SOURCE_FILTER_DIALOG_TAG = "source_filter_dialog"
TARGET_FILTER_DIALOG_TAG = "target_filter_dialog"
EXPORT_DIALOG_TAG = "export_dialog"
MAIN_WINDOW_TAG = "main_window"
CONTENT_AREA_TAG = "content_area"
INTERACTIVE_PANEL_TAG = "interactive_group"
INTERACTIVE_TABLE_TAG = "interactive_table"
SKIP_CONTINUE_BUTTON_TAG = "skip_continue_button"
CONFIRM_CREATE_MODAL_TAG = "confirm_create_modal"
FILE_EXPLORER_PANEL_TAG = "file_explorer"
HEADER_TAG = "header"
FOOTER_TAG = "footer"

SOURCE_FILTER_VIEW_TAG = "source_filter_view"
TARGET_FILTER_VIEW_TAG = "target_filter_view"
FILTERS_PANEL_TAG = "filters_panel"


PAIRS_ARE_NOT_LOADED_MSG = "Pairs are not loaded"
LAYOUT_VERTICAL_SAFETY = 8
FILTER_BOX_HEIGHT = 90
BUTTON_WIDTH = 140
HEADER_HEIGHT = 30
FOOTER_HEIGHT = HEADER_HEIGHT
FILE_EXPLORER_PANEL_SIZE = 90

WORD_HEIGHT = 28
SPACER_HEIGHT = 5

LOADING_W = 320
LOADING_H = 160

viewmodel = SemordnilapViewModel()


def _on_viewport_resize(sender, app_data):
    vw = dpg.get_viewport_width()
    vh = dpg.get_viewport_height()

    usable_h = vh - HEADER_HEIGHT * 2 - FOOTER_HEIGHT

    content_h = int(usable_h * 0.6)
    filters_h = usable_h - content_h

    # HEADER
    dpg.configure_item(HEADER_TAG, width=vw, height=HEADER_HEIGHT)

    # CONTENT_AREA
    dpg.configure_item(CONTENT_AREA_TAG, width=vw, height=content_h)

    # FILTERS_PANEL
    dpg.configure_item(FILTERS_PANEL_TAG, width=vw, height=filters_h)

    # FOOTER
    dpg.configure_item(FOOTER_TAG, width=vw, height=FOOTER_HEIGHT)


# -------------------------------- Utils ----------------------------- #


def _set_status(text, ok=True):
    dpg.set_value(STATUS_TAG, text)
    dpg.configure_item(
        STATUS_TAG, color=(120, 220, 120, 255) if ok else (220, 120, 120, 255)
    )


# -------------------------------- Callbacks ------------------------- #
def _on_semordnilaps_selected(_, app_data):
    path = app_data["file_path_name"]

    try:
        json_data = load_semordnilaps(path)
        viewmodel.set_semordnilaps(json_data)
        dpg.set_value(SEMORDNILAPS_TAG, path)
        _set_status(f"Loaded semordnilaps file", ok=True)
    except FileNotFoundError as e:
        viewmodel.set_semordnilaps(None)
        dpg.set_value(SEMORDNILAPS_TAG, "No file selected")
        _set_status(f"Invalid file: {e}", ok=False)


def _on_source_filter_words_selected(_, app_data):
    _on_filter_words_seleted(app_data, Axis.SOURCE)


def _on_target_filter_words_selected(_, app_data):
    _on_filter_words_seleted(app_data, Axis.TARGET)


def _on_filter_words_seleted(app_data, axis: Axis):
    path = app_data["file_path_name"]
    filepath = Path(path)

    try:
        if filepath.exists():
            viewmodel.load_filter_words(path, axis)
        else:
            dpg.set_value("_pending_filter_path", str(filepath))
            dpg.set_value("_pending_filter_axis", axis.value)
            dpg.show_item(CONFIRM_CREATE_MODAL_TAG)

        _refresh_persistent_filters_path_view()
        _refresh_persistent_filters_view()
    except Exception as e:
        _set_status(f"Error loading filter words: {e}", ok=False)


def _on_filter():

    if not viewmodel.pairs_loaded():
        _set_status(PAIRS_ARE_NOT_LOADED_MSG, ok=False)
        return

    _ui_block()
    try:
        viewmodel.apply_all_filters()
        viewmodel.reset_cursor()

        _refresh_pairs_list()
        _refresh_interactive_pairs_table()

        _ui_unblock()
        _on_filtering_end(
            viewmodel.len_base_pairs(), len(viewmodel.get_pairs_view())
        )
    except Exception as e:
        _set_status(str(e), ok=False)


def _on_ngram_size_selected(app_data, axis):
    if app_data == "All":
        ngram_size = 0
    else:
        ngram_size = int(app_data)
    viewmodel.set_ngram_size(ngram_size, axis=axis)

    _set_status(
        f"Selected N-gram filter {viewmodel.get_ngram_size(axis)}. Please filter your entries to apply this filter.",
        ok=True,
    )


def _on_source_ngram_size_selected(sender, app_data):
    _on_ngram_size_selected(app_data, Axis.SOURCE)


def _on_target_ngram_size_selected(sender, app_data):
    _on_ngram_size_selected(app_data, Axis.TARGET)


def _on_load_pairs():

    if not viewmodel.semordnilaps_loaded():
        _set_status("Semordnilaps not loaded", ok=False)
        return

    try:
        viewmodel.load_pairs()
        viewmodel.reset_cursor()
        _refresh_pairs_list()
        _refresh_interactive_pairs_table()

        _set_status(
            f"Loaded pairs ({viewmodel.len_base_pairs()} entries)", ok=True
        )

    except ValueError as e:
        _set_status(str(e), ok=False)


def _on_create_output_file():
    path = dpg.get_value("_pending_filter_path")
    axis = Axis(dpg.get_value("_pending_filter_axis"))

    file_path = Path(path)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)

        viewmodel.load_filter_words(path, axis)

        if axis == Axis.SOURCE:
            dpg.set_value(SOURCE_WORDS_FILTER_TAG, str(file_path))

        elif axis == Axis.TARGET:
            dpg.set_value(TARGET_WORDS_FILTER_TAG, str(file_path))

        else:
            raise RuntimeError("Unknown filter axis")

        _set_status(
            f"{axis.capitalize()} output file created and loaded",
            ok=True,
        )

    except Exception as e:
        _set_status(f"Error creating file: {e}", ok=False)

    finally:
        dpg.hide_item(CONFIRM_CREATE_MODAL_TAG)
        dpg.set_value("_pending_output_path", "")
        dpg.set_value("_pending_filter_axis", "")


def _on_next_pair():
    viewmodel.next_pair()
    _refresh_interactive_pairs_table()


def _on_filter_word(word: str, axis: Axis):

    viewmodel.add_candidate_filter_word(word, axis)

    _ui_block()

    viewmodel.filter_words({word}, axis)
    _refresh_pairs_list()

    _ui_unblock()

    _on_filtering_end(
        viewmodel.len_base_pairs(), len(viewmodel.get_pairs_view())
    )

    _refresh_candidate_filters_view()
    _refresh_interactive_pairs_table()


def _on_filter_source_word(word: str):
    _on_filter_word(word, axis=Axis.SOURCE)


def _on_filter_target_word(word: str):
    _on_filter_word(word, axis=Axis.TARGET)


# def _on_filtering_progress(i: int, total: int):
#     percent = int(i / total * 100)
#     _set_status(f'Filtering words"… {percent}% ({i}/{total})', ok=True)
#     dpg.split_frame()


def _on_filtering_end(src_total: int, dst_total: int):
    percentaje = (src_total - dst_total) / src_total * 100
    _set_status(
        f"Filtered: {src_total - dst_total}/{src_total} ({percentaje:.0f}%) entries - Keeped: {dst_total} entries",
        ok=True,
    )


def _on_pair_selected(sender, app_data, user_data):
    # Not working. Expected behaviour, when selecting a pair from the list
    # it should update the interactive panel.
    index = int(user_data)
    viewmodel.set_current_index(index)
    _refresh_interactive_pairs_table()


def _refresh_persistent_filters_view():
    dpg.delete_item(SOURCE_FILTER_VIEW_TAG, children_only=True)
    dpg.delete_item(TARGET_FILTER_VIEW_TAG, children_only=True)

    source_words, _ = viewmodel.get_word_filter(Axis.SOURCE)
    target_words, _ = viewmodel.get_word_filter(Axis.TARGET)

    if source_words:
        for word in sorted(
            source_words,
            key=lambda s: (len(s.split()), len(s)),
        ):
            dpg.add_text(word, parent=SOURCE_FILTER_VIEW_TAG)

        dpg.set_value(
            "source_loaded_label",
            f"Loaded (Total: {len(source_words)})",
        )

    if target_words:
        dpg.add_separator(parent=TARGET_FILTER_VIEW_TAG)

        for word in sorted(
            target_words,
            key=lambda s: (len(s.split()), len(s)),
        ):
            dpg.add_text(word, parent=TARGET_FILTER_VIEW_TAG)

        dpg.set_value(
            "target_loaded_label",
            f"Loaded (Total: {len(target_words)})",
        )


def _refresh_persistent_filters_path_view():
    _, source_path = viewmodel.get_word_filter(Axis.SOURCE)
    _, target_path = viewmodel.get_word_filter(Axis.TARGET)

    dpg.set_value(
        SOURCE_WORDS_FILTER_TAG,
        source_path if source_path else "No file selected",
    )

    dpg.set_value(
        TARGET_WORDS_FILTER_TAG,
        target_path if target_path else "No file selected",
    )


def _refresh_pairs_list():
    if not viewmodel.pairs_loaded():
        return

    dpg.delete_item("semordnilaps_list", children_only=True)

    for idx in range(viewmodel.len_active_pairs()):
        source, target = viewmodel.get_active_pair(idx)

        dpg.add_button(
            label=f"{source} <-> {target}",
            parent="semordnilaps_list",
            width=-1,
            height=WORD_HEIGHT,
            user_data=idx,
            callback=_on_pair_selected,
        )


def _refresh_candidate_filters_view():

    dpg.delete_item("selected_source_filters", children_only=True)
    dpg.delete_item("selected_target_filters", children_only=True)

    for word in viewmodel.get_candidate_filter_words(Axis.SOURCE):
        dpg.add_text(word, parent="selected_source_filters")

    for word in viewmodel.get_candidate_filter_words(Axis.TARGET):
        dpg.add_text(word, parent="selected_target_filters")


def _save_filters(axis: Axis):

    selected_words = viewmodel.get_candidate_filter_words(axis)
    if viewmodel.persistent_filter_words_loaded(axis) and selected_words:
        current_words, path = viewmodel.get_word_filter(axis)

        for word in sorted(selected_words):
            append_word_if_missing(
                filepath=path,
                word=word,
                current_words=current_words,
            )

        viewmodel.clear_candidate_filter_words(axis)
        viewmodel.load_filter_words(path, axis)

    _refresh_persistent_filters_view()
    _refresh_candidate_filters_view()


# -------------------------------------------------------------------- #


def _open_file_dialog(tag):
    dpg.show_item(tag)


def _export_pairs_to_file(path: str):
    pairs = viewmodel.get_pairs_view()
    if not pairs:
        _set_status("No pairs to export", ok=False)
        return
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


def _ui_block():
    _center_window("loading_overlay", LOADING_W, LOADING_H)
    dpg.show_item("loading_overlay")
    dpg.disable_item(INTERACTIVE_PANEL_TAG)

    dpg.split_frame()


def _ui_unblock():
    dpg.hide_item("loading_overlay")
    dpg.enable_item(INTERACTIVE_PANEL_TAG)


def _center_window(tag: str, width: int, height: int):
    vw = dpg.get_viewport_width()
    vh = dpg.get_viewport_height()
    dpg.set_item_pos(
        tag,
        [(vw - width) // 2, (vh - height) // 2],
    )


def _refresh_interactive_pairs_table():
    _refresh_ngram_buttons(
        tag_prefix="source_ngram",
        ngram=viewmodel.get_current_ngram(Axis.SOURCE),
        on_click=_on_filter_source_word,
    )

    _refresh_ngram_buttons(
        tag_prefix="target_ngram",
        ngram=viewmodel.get_current_ngram(Axis.TARGET),
        on_click=_on_filter_target_word,
    )


def _refresh_ngram_buttons(tag_prefix: str, ngram: Ngram, on_click: callable):
    ngram_phrase = ngram.get_ngram()
    tokens = ngram.get_tokens()
    n = max(len(tokens), 1)

    def _callback(sender, app_data, user_data):
        on_click(user_data)

    dpg.configure_item(
        f"{tag_prefix}_phrase",
        label=ngram_phrase,
        user_data=ngram_phrase,
        callback=_callback,
    )

    table = f"{tag_prefix}_tokens_table"

    dpg.delete_item(table, children_only=True)

    if n >= 2:
        cols = max(len(tokens), 1)
        for _ in range(cols):
            dpg.add_table_column(parent=table, init_width_or_weight=1)

        with dpg.table_row(parent=table):
            if tokens:
                for token in tokens:
                    dpg.add_button(
                        label=token,
                        width=-1,
                        height=WORD_HEIGHT,
                        user_data=token,
                        callback=_callback,
                    )


# ------------------------------- UI --------------------------------- #


def _build_ngram_buttons(parent: str, tag_prefix: str):
    with dpg.group(parent=parent, tag=f"{tag_prefix}_root"):
        dpg.add_button(
            tag=f"{tag_prefix}_phrase",
            label="",
            width=-1,
            height=WORD_HEIGHT,
        )

        dpg.add_spacer(height=SPACER_HEIGHT)

        with dpg.table(
            tag=f"{tag_prefix}_tokens_table",
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
            width=-1,
        ):
            dpg.add_table_column(init_width_or_weight=1)

            with dpg.table_row(tag=f"{tag_prefix}_tokens_row"):
                dpg.add_spacer(height=SPACER_HEIGHT)


def _build_source_target_table():
    with dpg.table(
        parent="interactive_table",
        tag="source_target_table",
        header_row=False,
        resizable=False,
        policy=dpg.mvTable_SizingStretchProp,
        width=-1,
    ):
        dpg.add_table_column(label="Source", init_width_or_weight=1)
        dpg.add_table_column(label="Target", init_width_or_weight=1)
        dpg.add_table_column(label="Actions", init_width_or_weight=0.6)

        with dpg.table_row():
            with dpg.group(tag="source_cell"):
                _build_ngram_buttons(
                    parent="source_cell",
                    tag_prefix="source_ngram",
                )

            with dpg.group(tag="target_cell"):
                _build_ngram_buttons(
                    parent="target_cell",
                    tag_prefix="target_ngram",
                )

            with dpg.group():
                dpg.add_button(
                    tag="like_button",
                    label="Like",
                    width=-1,
                    height=WORD_HEIGHT,
                    callback=_on_next_pair,
                )

                dpg.add_spacer(height=SPACER_HEIGHT)

                dpg.add_button(
                    tag=SKIP_CONTINUE_BUTTON_TAG,
                    label="Skip / Continue",
                    width=-1,
                    height=WORD_HEIGHT,
                    callback=_on_next_pair,
                )


def _build_confirm_create_file_modal():

    with dpg.window(
        label="Confirm file creation",
        modal=True,
        show=False,
        tag=CONFIRM_CREATE_MODAL_TAG,
        no_title_bar=False,
        width=400,
        height=120,
    ):
        dpg.add_text("The file does not exist.\nDo you want to create it?")
        dpg.add_spacer(height=SPACER_HEIGHT)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Yes", callback=_on_create_output_file)
            dpg.add_button(
                label="No",
                callback=lambda: dpg.hide_item(CONFIRM_CREATE_MODAL_TAG),
            )


def _build_loading_window():
    with dpg.window(
        tag=LOADING_OVERLAY_TAG,
        modal=True,
        show=False,
        no_title_bar=True,
        no_move=True,
        no_resize=True,
        no_close=True,
        no_scrollbar=True,
        width=LOADING_W,
        height=LOADING_H,
    ):
        with dpg.table(
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
            width=-1,
        ):
            dpg.add_table_column(init_width_or_weight=1)
            dpg.add_table_column(init_width_or_weight=0)
            dpg.add_table_column(init_width_or_weight=1)

            with dpg.table_row():
                dpg.add_text("")
                dpg.add_text("Filtering… please wait")
                dpg.add_text("")

            with dpg.table_row():
                dpg.add_text("")
                dpg.add_spacer(height=SPACER_HEIGHT)
                dpg.add_text("")

            with dpg.table_row():
                dpg.add_text("")
                dpg.add_loading_indicator()
                dpg.add_text("")

            with dpg.table_row():
                dpg.add_text("")
                dpg.add_spacer(height=SPACER_HEIGHT)
                dpg.add_text("")

            with dpg.table_row():
                dpg.add_text("")
                dpg.add_button(
                    label="Cancel",
                    width=100,
                    callback=lambda: None,
                )
                dpg.add_text("")


def _build_file_dialogs():
    with dpg.file_dialog(
        directory_selector=False,
        show=False,
        callback=_on_semordnilaps_selected,
        tag=SEMORDNILAPS_DIALOG_TAG,
        user_data=SEMORDNILAPS_TAG,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".json")

    with dpg.file_dialog(
        show=False,
        callback=_on_source_filter_words_selected,
        tag=SOURCE_FILTER_DIALOG_TAG,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")

    with dpg.file_dialog(
        show=False,
        callback=_on_target_filter_words_selected,
        tag=TARGET_FILTER_DIALOG_TAG,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")

    with dpg.file_dialog(
        show=False,
        callback=_export_dialog_selected,
        tag=EXPORT_DIALOG_TAG,
        directory_selector=False,
        modal=True,
        width=700,
        height=400,
    ):
        dpg.add_file_extension(".txt")


def _build_action_buttons():
    with dpg.group(
        horizontal=True,
        show=True,
    ):
        dpg.add_button(
            label="Load pairs",
            width=110,
            callback=_on_load_pairs,
        )
        dpg.add_button(
            label="Filter",
            width=110,
            callback=_on_filter,
        )
        dpg.add_button(
            label="Export",
            width=110,
            callback=lambda: dpg.show_item("export_dialog"),
        )


def _build_file_explorer():
    with dpg.collapsing_header(
        label="Files and Filters",
        default_open=True,
        tag=FILE_EXPLORER_PANEL_TAG,
    ):
        with dpg.table(
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingFixedFit,
            borders_innerV=True,
        ):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=220)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=90)

            # Semordnilaps
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
                    callback=lambda: _open_file_dialog("semordnilaps_dialog"),
                )

            # Source filter
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
                    callback=lambda: dpg.show_item("source_filter_dialog"),
                )

            # Target filter
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
                    callback=lambda: dpg.show_item("target_filter_dialog"),
                )

        dpg.add_spacer(height=0)

        # Ngram size selectors
        with dpg.group(horizontal=True):
            dpg.add_text("Source N-gram size:")
            dpg.add_combo(
                items=["All", "1", "2", "3"],
                default_value="All",
                width=120,
                callback=_on_source_ngram_size_selected,
            )

            dpg.add_spacer(width=20)

            dpg.add_text("Target N-gram size:")
            dpg.add_combo(
                items=["All", "1", "2", "3"],
                default_value="All",
                width=120,
                callback=_on_target_ngram_size_selected,
            )
            dpg.add_text("")


def _build_interactive_panel():
    with dpg.group(show=True, tag=INTERACTIVE_PANEL_TAG):
        with dpg.table(
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
            width=-1,
        ):
            dpg.add_table_column(label="Interactive", init_width_or_weight=1)
            dpg.add_table_column(label="Semordnilaps", init_width_or_weight=1)

            with dpg.table_row():
                with dpg.group():
                    _build_source_target_table()

                with dpg.child_window(
                    tag="semordnilaps_list",
                    border=True,
                    height=-1,
                    autosize_x=True,
                ):
                    pass


def _build_registries():
    with dpg.value_registry():
        dpg.add_string_value(tag=PENDING_FILTER_TAG, default_value="")
        dpg.add_string_value(tag=PENDING_FILTER_KIND_TAG, default_value="")


def _build_filters_panel():
    with dpg.child_window(
        tag=FILTERS_PANEL_TAG,
        border=True,
        autosize_x=True,
        width=-1,
        no_scrollbar=True,
    ):
        dpg.add_text("Filters")
        dpg.add_separator()

        with dpg.table(
            header_row=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
            width=-1,
            borders_innerV=True,
        ):
            dpg.add_table_column()
            dpg.add_table_column()

            with dpg.table_row():
                # ================= SOURCE =================
                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_text("Source Filters")
                        dpg.add_spacer(width=10)
                        dpg.add_button(
                            label="Save",
                            width=BUTTON_WIDTH,
                            callback=lambda: _save_filters(Axis.SOURCE),
                        )

                    dpg.add_spacer(height=4)

                    with dpg.child_window(height=-1, border=False):
                        with dpg.table(
                            header_row=False,
                            resizable=False,
                            policy=dpg.mvTable_SizingStretchProp,
                            width=-1,
                        ):
                            dpg.add_table_column()
                            dpg.add_table_column()

                            with dpg.table_row():
                                dpg.add_text("Selected")
                                dpg.add_text(
                                    "Loaded (Total: 0)",
                                    tag="source_loaded_label",
                                )

                            with dpg.table_row():
                                with dpg.child_window(
                                    tag="selected_source_filters",
                                    height=-1,
                                    border=True,
                                ):
                                    pass

                                with dpg.child_window(
                                    tag=SOURCE_FILTER_VIEW_TAG,
                                    height=-1,
                                    border=True,
                                ):
                                    pass

                # ================= TARGET =================
                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_text("Target Filters")
                        dpg.add_spacer(width=10)
                        dpg.add_button(
                            label="Save",
                            width=BUTTON_WIDTH,
                            callback=lambda: _save_filters(Axis.TARGET),
                        )

                    dpg.add_spacer(height=4)

                    with dpg.child_window(height=-1, border=False):
                        with dpg.table(
                            header_row=False,
                            resizable=False,
                            policy=dpg.mvTable_SizingStretchProp,
                            width=-1,
                        ):
                            dpg.add_table_column()
                            dpg.add_table_column()

                            with dpg.table_row():
                                dpg.add_text("Selected")
                                dpg.add_text(
                                    "Loaded (Total: 0)",
                                    tag="target_loaded_label",
                                )

                            with dpg.table_row():
                                with dpg.child_window(
                                    tag="selected_target_filters",
                                    height=-1,
                                    border=True,
                                ):
                                    pass

                                with dpg.child_window(
                                    tag=TARGET_FILTER_VIEW_TAG,
                                    height=-1,
                                    border=True,
                                ):
                                    pass


def _build_main_window():
    with dpg.window(
        tag=MAIN_WINDOW_TAG,
        label="Semordnilaps filtering engine",
        no_title_bar=True,
        no_resize=True,
        no_move=True,
    ):
        # HEADER
        with dpg.child_window(
            tag=HEADER_TAG,
            border=True,
            autosize_x=True,
            height=HEADER_HEIGHT,
        ):
            with dpg.group(horizontal=True):
                dpg.add_text("Status:", color=(180, 180, 180))
                dpg.add_text("", tag=STATUS_TAG)

        # CONTENT
        with dpg.child_window(
            tag=CONTENT_AREA_TAG,
            border=False,
            autosize_x=True,
            height=1,
        ):
            _build_file_explorer()
            dpg.add_spacer(height=SPACER_HEIGHT)

            _build_action_buttons()
            dpg.add_spacer(height=SPACER_HEIGHT)
            with dpg.child_window(
                height=-1,
                border=False,
            ):
                _build_interactive_panel()

        # FILTERS
        _build_filters_panel()

        # FOOTER
        with dpg.child_window(
            tag=FOOTER_TAG,
            border=False,
            autosize_x=True,
            height=FOOTER_HEIGHT,
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


def build_ui():
    dpg.set_viewport_resize_callback(_on_viewport_resize)
    _build_registries()
    _build_loading_window()
    _build_file_dialogs()
    _build_confirm_create_file_modal()
    _build_main_window()
