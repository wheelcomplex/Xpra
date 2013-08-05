# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os.path

from xpra.log import Logger
log = Logger()

from xpra.platform.win32.paths import get_icon_dir
from xpra.gtk_common.gobject_compat import import_gdk
gdk = import_gdk()


def get_native_notifier_classes():
    from xpra.platform.win32.win32_notifier import Win32_Notifier
    return [Win32_Notifier]


def make_native_tray(tooltip, delay_tray, tray_icon, activate_cb, quit_cb):
    from xpra.platform.win32.win32_tray import Win32Tray

    if not tray_icon or not os.path.exists(tray_icon):
        tray_icon = os.path.join(get_icon_dir(), 'xpra.ico')
    if not tray_icon or not os.path.exists(tray_icon):
        log.error("invalid tray icon filename: '%s'" % tray_icon)

    def tray_exit(*args):
        log("tray_exit() calling %s", quit_cb)
        quit_cb()

    def tray_activate(*args):
        log("tray_activate() calling %s", activate_cb)
        activate_cb()

    return Win32Tray(tooltip, tray_activate, tray_exit, tray_icon)


class ClientExtras(object):
    def __init__(self, client, opts, conn):
        self.setup_console_event_listener()

    def cleanup(self):
        self.setup_console_event_listener(False)
        log("ClientExtras.cleanup() ended")

    def setup_console_event_listener(self, enable=1):
        try:
            import win32api     #@UnresolvedImport
            result = win32api.SetConsoleCtrlHandler(self.handle_console_event, enable)
            if result == 0:
                log.error("could not SetConsoleCtrlHandler (error %r)", win32api.GetLastError())
        except:
            pass

    def handle_console_event(self, event):
        log("handle_console_event(%s)", event)
        import win32con         #@UnresolvedImport
        events = {win32con.CTRL_C_EVENT         : "CTRL_C",
                  win32con.CTRL_LOGOFF_EVENT    : "LOGOFF",
                  win32con.CTRL_BREAK_EVENT     : "BREAK",
                  win32con.CTRL_SHUTDOWN_EVENT  : "SHUTDOWN",
                  win32con.CTRL_CLOSE_EVENT     : "CLOSE"
                  }
        if event in events:
            log.info("received win32 console event %s", events.get(event))
        return 0
