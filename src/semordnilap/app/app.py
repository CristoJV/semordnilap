import dearpygui.dearpygui as dpg

from semordnilap.app.ui.main_window import build_ui


def run():
    dpg.create_context()

    build_ui()

    dpg.create_viewport(
        title="Semordnilaps filtering engine", width=1024, height=720
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()
