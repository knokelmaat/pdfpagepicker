import json
import os
import platform
from pathlib import Path
from typing import Any, Mapping

from pypdfium2 import PdfDocument

import gi

gi.require_version(namespace="Gtk", version="4.0")
gi.require_version(namespace="Adw", version="1")

from gi.repository import Adw, Gio, GLib, Gtk

Adw.init()

TITLE = "Pdf Mixer"

APP_ID = "me.proton.vda.christophe.pdfmixer"


class ConfigHandler:
    def __init__(self, app_name: str) -> None:
        self._app_name = app_name

    def _get_config_dir(self) -> None:
        system = platform.system()

        if system == "Windows":
            base = os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming"
            config_path = Path(base) / self._app_name

        elif system == "Darwin":  # macOS
            config_path = (
                Path.home() / "Library" / "Application Support" / self._app_name
            )

        else:  # Assume Linux / other Unix‑like
            xdg = os.getenv("XDG_CONFIG_HOME")
            if xdg:
                config_path = Path(xdg) / self._app_name
            else:
                config_path = Path.home() / ".config" / self._app_name

        # Make sure the directory exists
        config_path.mkdir(parents=True, exist_ok=True)
        return config_path

    def save_settings(
        self, settings: Mapping[str, Any], filename: str = "settings.json"
    ) -> None:
        config_dir = self._get_config_dir()
        target_file = config_dir / filename

        with target_file.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, sort_keys=True, ensure_ascii=False)

    def load_settings(self, filename: str = "settings.json") -> Mapping[str, Any]:
        config_dir = self._get_config_dir()
        target_file = config_dir / filename

        try:
            with target_file.open("r", encoding="utf-8") as f:
                settings = json.load(f)
        except FileNotFoundError:
            settings = {}

        return settings


class Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.input_folder = None
        self.input_file = None
        self.output_folder = None
        self.selection = []

        self.source_doc = None
        self.pages = []

        self.set_title(title=TITLE)
        self.set_default_size(width=683, height=384)
        self.set_size_request(width=683, height=384)

        adw_toolbar_view = Adw.ToolbarView.new()
        self.set_content(content=adw_toolbar_view)

        # Top Bar.
        adw_header_bar = Adw.HeaderBar.new()
        open_file_button = Gtk.Button.new_with_label("Open Source PDF")
        open_file_button.connect("clicked", self._present_open_dialog)
        adw_header_bar.pack_start(open_file_button)
        generate_button = Gtk.Button.new_with_label("Generate New PDF")
        generate_button.connect("clicked", self._present_save_dialog)
        adw_header_bar.pack_end(generate_button)
        adw_toolbar_view.add_top_bar(widget=adw_header_bar)

        # Content.
        scrolled_window = Gtk.ScrolledWindow()
        adw_toolbar_view.set_content(content=scrolled_window)

        clamp = Adw.Clamp(maximum_size=500)
        scrolled_window.set_child(clamp)

        self.page_list = Gtk.ListBox(
            margin_top=16, margin_bottom=16, valign=Gtk.Align.START
        )
        self.page_list.add_css_class("boxed-list")
        clamp.set_child(self.page_list)

        empty_list_status_page = Adw.StatusPage(
            title="No PDF loaded.",
            description='Click the "Open Source PDF" button to load a template PDF file.',
        )
        self.page_list.set_placeholder(empty_list_status_page)

        self._init_open_dialog()
        self._init_save_dialog()

        self._config_handler = ConfigHandler(APP_ID)
        self._load_configuration()
        app = self.get_application()
        if app:
            app.connect("shutdown", self._save_configuration)

        self._process_input_file()
        self._apply_selection()

    def _init_open_dialog(self):
        self.open_dialog = Gtk.FileDialog()
        self.open_dialog.set_title("Select a PDF file")

        self.open_dialog.set_accept_label("Open")
        self.open_dialog.set_modal(True)

        pdf_filter = Gtk.FileFilter()
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_pattern("*.pdf")
        pdf_filter.set_name("PDF documents")
        self.open_dialog.set_default_filter(pdf_filter)

        documents_dir = GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOCUMENTS
        )
        if documents_dir:
            self.open_dialog.set_initial_folder(Gio.File.new_for_path(documents_dir))

    def _init_save_dialog(self):
        self.save_dialog = Gtk.FileDialog()
        self.save_dialog.set_title("Choose a location to save.")

        self.save_dialog.set_accept_label("Save")
        self.save_dialog.set_modal(True)

        pdf_filter = Gtk.FileFilter()
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_pattern("*.pdf")
        pdf_filter.set_name("PDF documents")
        self.save_dialog.set_default_filter(pdf_filter)

        documents_dir = GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOCUMENTS
        )
        if documents_dir:
            self.save_dialog.set_initial_folder(
                self.input_folder or Gio.File.new_for_path(documents_dir)
            )

    def _load_configuration(self):
        settings = self._config_handler.load_settings()

        input_file_path = settings.get("input_file")
        if input_file_path:
            self.input_file = Gio.File.new_for_path(input_file_path)
            if not self.input_file.query_exists():
                self.input_file = None

        input_folder_path = settings.get("input_folder")
        if input_folder_path:
            self.input_folder = Gio.File.new_for_path(input_folder_path)
            if not self.input_folder.query_exists():
                self.input_folder = None

        output_folder_path = settings.get("output_folder")
        if output_folder_path:
            self.output_folder = Gio.File.new_for_path(output_folder_path)
            if not self.output_folder.query_exists():
                self.output_folder = None

        documents_folder_path = GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOCUMENTS
        )
        if documents_folder_path:
            documents_folder = Gio.File.new_for_path(documents_folder_path)

            if self.input_folder is None:
                self.input_folder = documents_folder
            if self.output_folder is None:
                self.output_folder = documents_folder

        self.selection = settings.get("selection") or []

    def _save_configuration(self, _app) -> None:
        settings = {}

        settings["input_file"] = self.input_file.get_path() if self.input_file else None
        settings["input_folder"] = (
            self.input_folder.get_path() if self.input_folder else None
        )
        settings["output_folder"] = (
            self.output_folder.get_path() if self.output_folder else None
        )
        settings["selection"] = self.selection

        self._config_handler.save_settings(settings=settings)

    def _present_open_dialog(self, _button):
        self.open_dialog.set_initial_folder(self.input_folder)

        self.open_dialog.open(
            parent=self, cancellable=None, callback=self._on_open_file
        )

    def _on_open_file(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult):
        try:
            # This will raise a GError if the user cancelled the dialog
            file = dialog.open_finish(result)
        except GLib.Error as e:
            # Cancelled – just exit silently
            return

        self.input_file = file
        self.input_folder = file.get_parent()
        self._process_input_file()

    def _process_input_file(self):
        if self.input_file is None:
            return

        self._import_pdf(self.input_file.get_path())
        self._generate_list()

    def _import_pdf(self, path):
        self.source_doc = PdfDocument(path)
        self.pages = []
        for page in self.source_doc:
            text = page.get_textpage().get_text_range()
            title = text.split("\n")[0]
            self.pages.append(title)

    def _generate_list(self):
        self.page_list.remove_all()
        for title in self.pages:
            self.page_list.append(Adw.SwitchRow(title=title))

    def _present_save_dialog(self, _button):
        self.save_dialog.set_initial_folder(self.output_folder)
        self.save_dialog.set_initial_name("output.pdf")

        self.save_dialog.save(
            parent=self, cancellable=None, callback=self._on_save_file
        )

    def _on_save_file(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult):
        try:
            # This will raise a GError if the user cancelled the dialog
            file = dialog.save_finish(result)
        except GLib.Error as e:
            # Cancelled – just exit silently
            return

        self.output_folder = file.get_parent()

        output_doc = self._generate_output_doc()
        output_doc.save(file.get_path())

        file_launcher = Gtk.FileLauncher(file=file)
        file_launcher.launch()

    def _generate_output_doc(self):
        self._update_selection()
        outputDoc = PdfDocument.new()
        outputDoc.import_pages(self.source_doc, pages=self.selection)
        return outputDoc

    def _update_selection(self):
        self.selection = []
        for index in range(len(self.pages)):
            if self.page_list.get_row_at_index(index).get_active():
                self.selection.append(index)

    def _apply_selection(self):
        if not self.selection or max(self.selection) >= len(self.pages):
            return
        for index in self.selection:
            self.page_list.get_row_at_index(index).set_active(True)


class Application(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

        self.create_action("quit", self.exit_app, ["<primary>q"])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = Window(application=self)
        win.present()

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def do_shutdown(self):
        Gtk.Application.do_shutdown(self)

    def exit_app(self, action, param):
        self.quit()

    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name=name, parameter_type=None)
        action.connect("activate", callback)
        self.add_action(action=action)
        if shortcuts:
            self.set_accels_for_action(
                detailed_action_name=f"app.{name}",
                accels=shortcuts,
            )


if __name__ == "__main__":
    import sys

    app = Application()
    app.run(sys.argv)
