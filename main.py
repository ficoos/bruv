#!/bin/env python3
import gi
gi.require_version('Gtk', '3.0')

import sys
import gui

from gi.repository import Gtk


def main():
    app = gui.BruvApplication()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
