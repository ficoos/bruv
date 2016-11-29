#!/bin/env python3
from gi.repository import Gtk, GLib, Gio

from gerrit import QueryOptions, Gerrit
import bruv


class Connection(object):
    def __init__(self, name, host, port, pkey):
        self.name = name
        self.host = host
        self.port = port
        self.pkey = pkey


class Query(object):
    def __init__(self, connection, name, query):
        self.connection = connection
        self.name = name
        self.query = query


def uiclass(path, window_id):
    def wrapper(cls):
        def factory(application, *args, **kwargs):
            builder = Gtk.Builder()
            builder.add_from_file(path)
            window = builder.get_object(window_id)
            instance = cls(builder, window, *args, **kwargs)
            builder.connect_signals(instance)
            application.add_window(window)
            return instance

        return factory

    return wrapper


@uiclass('MainWindow.ui', 'MainWindow')
class MainWindow(object):
    def __init__(self, builder, window):
        self._builder = builder
        self._source_store = builder.get_object('source_store')
        self._source_tree_view = builder.get_object('source_tree_view')
        self._source_tree_view.append_column(Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0))
        self._source_tree_view.append_column(Gtk.TreeViewColumn("Count", Gtk.CellRendererText(), text=1))
        self._window = window
        self._window.show_all()

    def on_focus(self, widget, event):
        self._source_store.clear()
        p = self._source_store.append(None, ['OpenStack', 30])
        self._source_store.append(p, ('Dragonflow', 15))
        self._source_store.append(p, ('Karbor', 15))

    def on_delete(self, widget, event):
        Gtk.Application.get_default().quit()

    def present(self):
        self._window.present()


class MainWindow_(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._conf = bruv.load_configuration()
        self._grid = Gtk.Grid()
        self._grid.set_column_homogeneous(True)
        self._grid.set_row_homogeneous(True)
        self._header = Gtk.HeaderBar()
        self._header.set_title("Bruv")
        self._header.set_subtitle("Make Gerrit graet again")
        label = Gtk.Label("Pack Start")
        self._header.pack_start(label)
        label = Gtk.Label("Pack End")
        self._header.pack_end(label)
        self.add(self._header)

        self.add(self._grid)

        self._store = Gtk.ListStore(str, str, str, str, str, str)
        self._changeset_view = Gtk.TreeView.new_with_model(self._store)
        for i, column_title in enumerate(["Flags", "Message", "Project", "Topic", "User Name", "URL"]):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(column_title, renderer, text=i)
            column.set_sort_column_id(i)
            self._changeset_view.append_column(column)

        self.scrollable_treelist = Gtk.ScrolledWindow()
        self.scrollable_treelist.set_vexpand(True)
        self.scrollable_treelist.add(self._changeset_view)

        self._grid.attach(self.scrollable_treelist, 0, 1, 400, 600)
        self.show_all()

    def update_list(self):
        self._gerrit = Gerrit(
            self._conf.host,
            self._conf.port,
            self._conf.username,
            self._conf.pkey)

        changesets = self._gerrit.query(
            self._conf.query,
            options=[QueryOptions.Comments,
                     QueryOptions.CurrentPatchSet,
                     QueryOptions.CommitMessage])
        self._store.clear()
        for change in changesets:
            self._store.append([
                '',
                change['subject'],
                change['project'],
                change.get('topic', 'no-topic'),
                '',
                '',
            ])


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
            self._window = MainWindow(self)

        self._window.present()

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def on_quit(self):
        self.quit()
