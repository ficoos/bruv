#!/bin/env python3
import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, GLib, Gio
import sys

from gerrit import QueryOptions, Gerrit
import bruv


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._conf = bruv.load_configuration()
        self._gerrit = Gerrit(
            self._conf.host,
            self._conf.port,
            self._conf.username,
            self._conf.pkey)

        self._grid = Gtk.Grid()
        self._grid.set_column_homogeneous(True)
        self._grid.set_row_homogeneous(True)
        self.add(self._grid)

        self._store = Gtk.ListStore(str, str, str, str, str, str)
        self._changeset_view = Gtk.TreeView.new_with_model(self._store)
        for i, column_title in enumerate(["Flags", "Message", "Project", "Topic", "User Name", "URL"]):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(column_title, renderer, text=i)
            self._changeset_view.append_column(column)

        self.scrollable_treelist = Gtk.ScrolledWindow()
        self.scrollable_treelist.set_vexpand(True)
        self.scrollable_treelist.add(self._changeset_view)

        self._grid.attach(self.scrollable_treelist, 0, 0, 8, 10)
        self.show_all()

    def update_list(self):
        changesets = self._gerrit.query(self._conf.query,
                      options=[QueryOptions.Comments,
                               QueryOptions.CurrentPatchSet,
                               QueryOptions.CommitMessage])
        self._store.clear()
        for change in changesets:
            self._store.append(
                '',
                change['message'],
                change['project'],
                change['topic'],
                '',
                '',
            )


class BruvApplication(Gtk.Application):
    def __init__(self,
                 application_id='org.ficoos.bruv',
                 flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE):
        super().__init__(application_id=application_id, flags=flags)

        GLib.set_application_name('Bruv')
        GLib.set_prgname('bruv')
        self._window = None

    def do_command_line(self, command_line):
        self.activate()
        return 0

    def do_activate(self):
        if self._window is None:
            self._window = MainWindow(application=self, title="Bruv")

        self._window.present()

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def on_quit(self):
        self.quit()

if __name__ == "__main__":
    app = BruvApplication()
    app.run(sys.argv)
