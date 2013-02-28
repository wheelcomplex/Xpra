# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject

# Maintain compatibility with old versions of Python, while avoiding a
# deprecation warning on new versions:
import sys
if sys.version_info < (2, 6):
    from sets import ImmutableSet
else:
    ImmutableSet = frozenset

from wimpiggy.error import trap
import wimpiggy.selection
from wimpiggy.world_window import WorldWindow
from wimpiggy.prop import prop_set, prop_get
from wimpiggy.util import no_arg_signal, one_arg_signal

from wimpiggy.window import WindowModel, Unmanageable
from wimpiggy.lowlevel import (
               const,                                       #@UnresolvedImport
               printFocus,                                  #@UnresolvedImport
               add_event_receiver,                          #@UnresolvedImport
               substructureRedirect,                        #@UnresolvedImport
               configureAndNotify,                          #@UnresolvedImport
               myGetSelectionOwner,                         #@UnresolvedImport
               get_children,                                #@UnresolvedImport
               get_xwindow,                                 #@UnresolvedImport
               is_override_redirect,                        #@UnresolvedImport
               is_mapped,                                   #@UnresolvedImport
               selectFocusChange,                           #@UnresolvedImport
               selectBellNotification,                      #@UnresolvedImport
               selectCursorChange,                          #@UnresolvedImport
               )

from wimpiggy.log import Logger
log = Logger()


def wm_check(display):
    #there should only be one screen... but let's check all of them
    for i in range(display.get_n_screens()):
        screen = display.get_screen(i)
        root = screen.get_root_window()
        prop = "WM_S%s" % i
        ewmh_so = myGetSelectionOwner(display, prop)
        log("ewmh selection owner for %s: %s", prop, ewmh_so)
    
        ewmh_wm = prop_get(root, "_NET_SUPPORTING_WM_CHECK", "window", ignore_errors=False, raise_xerrors=False)
        log("_NET_SUPPORTING_WM_CHECK for screen %s: %s", i, ewmh_wm)
        if ewmh_wm:
            name = prop_get(ewmh_wm, "_NET_WM_NAME", "utf8", ignore_errors=False, raise_xerrors=False)
            log.warn("Warning: found an existing window manager on screen %s using window id %s: %s", i, hex(get_xwindow(ewmh_wm)), name or "unnamed")
            if ewmh_so is None or ewmh_so==0:
                log.error("it does not own the selection '%s' so we cannot take over and make it exit", prop)
                log.error("please stop %s so you can run xpra on this display", name or "the existing window manager")
                return False
    return True


class Wm(gobject.GObject):
    _NET_SUPPORTED = [
        "_NET_SUPPORTED", # a bit redundant, perhaps...
        "_NET_SUPPORTING_WM_CHECK",
        "_NET_WM_FULL_PLACEMENT",
        "_NET_WM_HANDLED_ICONS",
        "_NET_CLIENT_LIST",
        "_NET_CLIENT_LIST_STACKING",
        "_NET_DESKTOP_VIEWPORT",
        "_NET_DESKTOP_GEOMETRY",
        "_NET_NUMBER_OF_DESKTOPS",
        "_NET_DESKTOP_NAMES",
        "_NET_WORKAREA",
        "_NET_ACTIVE_WINDOW",
        "_NET_CURRENT_DESKTOP",

        "WM_NAME", "_NET_WM_NAME",
        "WM_ICON_NAME", "_NET_WM_ICON_NAME",
        "WM_CLASS",
        "WM_PROTOCOLS",
        "_NET_WM_PID",
        "WM_CLIENT_MACHINE",
        "WM_STATE",

        "_NET_WM_ALLOWED_ACTIONS",
        "_NET_WM_ACTION_CLOSE",

        # We don't actually use _NET_WM_USER_TIME at all (yet), but it is
        # important to say we support the _NET_WM_USER_TIME_WINDOW property,
        # because this tells applications that they do not need to constantly
        # ping any pagers etc. that might be running -- see EWMH for details.
        # (Though it's not clear that any applications actually take advantage
        # of this yet.)
        "_NET_WM_USER_TIME",
        "_NET_WM_USER_TIME_WINDOW",
        # Not fully:
        "WM_HINTS",
        "WM_NORMAL_HINTS",
        "WM_TRANSIENT_FOR",
        "_NET_WM_STRUT",
        "_NET_WM_STRUT_PARTIAL"
        "_NET_WM_ICON",

        # These aren't supported in any particularly meaningful way, but hey.
        "_NET_FRAME_EXTENTS",

        "_NET_WM_WINDOW_TYPE",
        "_NET_WM_WINDOW_TYPE_NORMAL",
        # "_NET_WM_WINDOW_TYPE_DESKTOP",
        # "_NET_WM_WINDOW_TYPE_DOCK",
        # "_NET_WM_WINDOW_TYPE_TOOLBAR",
        # "_NET_WM_WINDOW_TYPE_MENU",
        # "_NET_WM_WINDOW_TYPE_UTILITY",
        # "_NET_WM_WINDOW_TYPE_SPLASH",
        # "_NET_WM_WINDOW_TYPE_DIALOG",
        # "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
        # "_NET_WM_WINDOW_TYPE_POPUP_MENU",
        # "_NET_WM_WINDOW_TYPE_TOOLTIP",
        # "_NET_WM_WINDOW_TYPE_NOTIFICATION",
        # "_NET_WM_WINDOW_TYPE_COMBO",
        # "_NET_WM_WINDOW_TYPE_DND",
        # "_NET_WM_WINDOW_TYPE_NORMAL",

        "_NET_WM_STATE",
        "_NET_WM_STATE_DEMANDS_ATTENTION",
        "_NET_WM_STATE_MODAL",
        # More states to support:
        # _NET_WM_STATE_STICKY,
        # _NET_WM_STATE_MAXIMIZED_VERT,
        # _NET_WM_STATE_MAXIMIZED_HORZ,
        # _NET_WM_STATE_SHADED,
        "_NET_WM_STATE_SKIP_TASKBAR",
        "_NET_WM_STATE_SKIP_PAGER",
        "_NET_WM_STATE_HIDDEN",
        "_NET_WM_STATE_FULLSCREEN",
        # _NET_WM_STATE_ABOVE,
        # _NET_WM_STATE_BELOW,

        # Not at all yet:
        #"_NET_REQUEST_FRAME_EXTENTS",
        #"_NET_CLOSE_WINDOW",
        #"_NET_RESTACK_WINDOW",
        #"_NET_WM_DESKTOP",
        ]

    __gproperties__ = {
        "windows": (gobject.TYPE_PYOBJECT,
                    "Set of managed windows (as WindowModels)", "",
                    gobject.PARAM_READABLE),
        "toplevel": (gobject.TYPE_PYOBJECT,
                     "Toplevel container widget for the display", "",
                     gobject.PARAM_READABLE),
        }
    __gsignals__ = {
        # Public use:
        # A new window has shown up:
        "new-window": one_arg_signal,
        # A window got resized:
        "window-resized": one_arg_signal,
        # X11 bell event:
        "bell": one_arg_signal,
        # You can emit this to cause the WM to quit, or the WM may
        # spontaneously raise it if another WM takes over the display.  By
        # default, unmanages all windows:
        "quit": no_arg_signal,
        # Emit this when the list of desktop names has changed:
        "desktop-list-changed": one_arg_signal,

        # Mostly intended for internal use:
        "child-map-request-event": one_arg_signal,
        "child-configure-request-event": one_arg_signal,
        "wimpiggy-focus-in-event": one_arg_signal,
        "wimpiggy-focus-out-event": one_arg_signal,
        "wimpiggy-client-message-event": one_arg_signal,
        "wimpiggy-xkb-event": one_arg_signal,
        }

    def __init__(self, name, replace_other_wm, display=None):
        gobject.GObject.__init__(self)

        self._name = name
        if display is None:
            display = gtk.gdk.display_manager_get().get_default_display()
        self._display = display
        self._alt_display = gtk.gdk.Display(self._display.get_name())
        self._root = self._display.get_default_screen().get_root_window()
        self._ewmh_window = None

        self._windows = {}
        # EWMH says we have to know the order of our windows oldest to
        # youngest...
        self._windows_in_order = []

        # Become the Official Window Manager of this year's display:
        self._wm_selection = wimpiggy.selection.ManagerSelection(self._display, "WM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        # May throw AlreadyOwned:
        if replace_other_wm:
            mode = self._wm_selection.FORCE
        else:
            mode = self._wm_selection.IF_UNOWNED
        self._wm_selection.acquire(mode)
        # (If we become a compositing manager, then we will want to do the
        # same thing with the _NET_WM_CM_S0 selection (says EWMH).  AFAICT
        # this basically will just be used by clients to know that they can
        # use RGBA visuals.)

        # Set up the necessary EWMH properties on the root window.
        self._setup_ewmh_window()
        # Start with just one desktop:
        self.do_desktop_list_changed([u"Main"])
        self.set_current_desktop(0)
        # Start with the full display as workarea:
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        self.set_workarea(0, 0, root_w, root_h)
        self.root_set("_NET_DESKTOP_VIEWPORT", ["u32"], [0, 0])
        self.root_set("_NET_SUPPORTED", ["atom"], self._NET_SUPPORTED)

        # Load up our full-screen widget
        self._world_window = WorldWindow()
        self._world_window.set_screen(self._display.get_default_screen())
        self.notify("toplevel")
        self._world_window.show_all()

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        add_event_receiver(self._root, self)
        substructureRedirect(self._root)

        import time
        children = None
        for _ in range(5):
            try:
                children = trap.call(get_children, self._root)
                log.info("children=%s", children)
                break
            except Exception, e:
                log.info("error getting the list of windows: %s", e)
                time.sleep(0.1)
        if children is None:
            raise Exception("failed to get the list of windows - maybe another window manager is running?")
        for w in children:
            # Checking for FOREIGN here filters out anything that we've
            # created ourselves (like, say, the world window), and checking
            # for mapped filters out any withdrawn windows.
            if (w.get_window_type() == gtk.gdk.WINDOW_FOREIGN
                and not is_override_redirect(w)
                and is_mapped(w)):
                log("Wm managing pre-existing child")
                self._manage_client(w)

        # Also watch for focus change events on the root window
        selectFocusChange(self._root)
        selectBellNotification(self._root, True)

        # FIXME:
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

    def root_set(self, *args):
        prop_set(self._root, *args)

    def set_workarea(self, x, y, width, height):
        self.root_set("_NET_WORKAREA", ["u32"], [x, y, width, height])

    def enableCursors(self, on):
        log("enableCursors(%s)" % on)
        selectCursorChange(self._root, on)

    def do_wimpiggy_xkb_event(self, event):
        log("wm.do_wimpiggy_xkb_event(%r)" % event)
        if event.type!="bell":
            log.error("wm.do_wimpiggy_xkb_event(%r) unknown event type: %s" % (event, event.type))
            return
        self.do_bell_event(event)

    def do_bell_event(self, event):
        self.emit("bell", event)

    def do_get_property(self, pspec):
        if pspec.name == "windows":
            return ImmutableSet(self._windows.itervalues())
        elif pspec.name == "toplevel":
            return self._world_window
        else:
            assert False

    # This is in some sense the key entry point to the entire WM program.  We
    # have detected a new client window, and start managing it:
    def _manage_client(self, gdkwindow):
        try:
            if gdkwindow not in self._windows:
                trap.call_synced(self.do_manage_client, gdkwindow)
        except Exception, e:
            log("failed to manage client %s: %s", gdkwindow, e)

    def do_manage_client(self, gdkwindow):
        try:
            win = WindowModel(self._root, gdkwindow)
        except Unmanageable:
            log("Window disappeared on us, never mind")
            return
        win.connect("unmanaged", self._handle_client_unmanaged)
        def bell_event(window_model, event):
            self.do_bell_event(event)
        win.connect("bell", bell_event)
        def geometry_changed(model, *args):
            log("Wm.geometry_changed(%s, %s) on window %s", model, args, win)
            self.emit("window-resized", win)
        win.connect("geometry", geometry_changed)
        self._windows[gdkwindow] = win
        self._windows_in_order.append(gdkwindow)
        self.notify("windows")
        self._update_window_list()
        self.emit("new-window", win)

    def _handle_client_unmanaged(self, window, wm_exiting):
        gdkwindow = window.get_property("client-window")
        assert gdkwindow in self._windows
        del self._windows[gdkwindow]
        self._windows_in_order.remove(gdkwindow)
        self._update_window_list()
        self.notify("windows")

    def _update_window_list(self, *args):
        # Ignore errors because not all the windows may still exist; if so,
        # then it's okay to leave the lists out of date for a moment, because
        # in a moment we'll get a signal telling us about the window that
        # doesn't exist anymore, will remove it from the list, and then call
        # _update_window_list again.
        trap.swallow_synced(self.root_set, "_NET_CLIENT_LIST",
                     ["window"], self._windows_in_order)
        # This is a lie, but we don't maintain a stacking order, so...
        trap.swallow_synced(self.root_set, "_NET_CLIENT_LIST_STACKING",
                     ["window"], self._windows_in_order)

    def do_wimpiggy_client_message_event(self, event):
        # FIXME
        # Need to listen for:
        #   _NET_CLOSE_WINDOW
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_REQUEST_FRAME_EXTENTS
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_DESKTOP
        #   _NET_WM_STATE
        log("do_wimpiggy_client_message_event(%s)", event)

    def _lost_wm_selection(self, selection):
        log.info("Lost WM selection, exiting")
        self.emit("quit")

    def do_quit(self):
        for win in list(self._windows.itervalues()):
            win.unmanage(True)

    def do_child_map_request_event(self, event):
        log("Found a potential client")
        self._manage_client(event.window)

    def do_child_configure_request_event(self, event):
        # The point of this method is to handle configure requests on
        # withdrawn windows.  We simply allow them to move/resize any way they
        # want.  This is harmless because the window isn't visible anyway (and
        # apps can create unmapped windows with whatever coordinates they want
        # anyway, no harm in letting them move existing ones around), and it
        # means that when the window actually gets mapped, we have more
        # accurate info on what the app is actually requesting.
        log("do_child_configure_request_event(%s)", event)
        if event.window in self._windows:
            return
        log("Reconfigure on withdrawn window")
        trap.swallow_synced(configureAndNotify,
                     event.window, event.x, event.y,
                     event.width, event.height,
                     event.value_mask)

    def do_wimpiggy_focus_in_event(self, event):
        # The purpose of this function is to detect when the focus mode has
        # gone to PointerRoot or None, so that it can be given back to
        # something real.  This is easy to detect -- a FocusIn event with
        # detail PointerRoot or None is generated on the root window.
        if event.detail in (const["NotifyPointerRoot"], const["NotifyDetailNone"]):
            self._world_window.reset_x_focus()

    def do_wimpiggy_focus_out_event(self, event):
        printFocus(self._display)

    def do_desktop_list_changed(self, desktops):
        self.root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
        self.root_set("_NET_DESKTOP_NAMES", ["utf8"], desktops)

    def set_current_desktop(self, index):
        self.root_set("_NET_CURRENT_DESKTOP", "u32", index)

    def _setup_ewmh_window(self):
        # Set up a 1x1 invisible unmapped window, with which to participate in
        # EWMH's _NET_SUPPORTING_WM_CHECK protocol.  The only important things
        # about this window are the _NET_SUPPORTING_WM_CHECK property, and
        # its title (which is supposed to be the name of the window manager).

        # NB, GDK will do strange things to this window.  We don't want to use
        # it for anything.  (In particular, it will call XSelectInput on it,
        # which is fine normally when GDK is running in a client, but since it
        # happens to be using the same connection as we the WM, it will
        # clobber any XSelectInput calls that *we* might have wanted to make
        # on this window.)  Also, GDK might silently swallow all events that
        # are detected on it, anyway.
        self._ewmh_window = gtk.gdk.Window(self._root,
                                           width=1,
                                           height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask=0, # event mask
                                           wclass=gtk.gdk.INPUT_ONLY,
                                           title="%s-EWMH" % self._name)
        prop_set(self._ewmh_window, "_NET_SUPPORTING_WM_CHECK",
                 "window", self._ewmh_window)
        self.root_set("_NET_SUPPORTING_WM_CHECK",
                 "window", self._ewmh_window)

    # Other global actions:

    def _make_window_pseudoclient(self, win):
        "Used by PseudoclientWindow, only."
        win.set_screen(self._alt_display.get_default_screen())

gobject.type_register(Wm)
