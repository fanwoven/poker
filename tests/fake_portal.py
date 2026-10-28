"""A tiny fake xdg-desktop-portal, to test our D-Bus conversation without GNOME.
Run inside 'dbus-run-session'. Answers CreateSession, SelectSources, Start,
OpenPipeWireRemote and Screenshot like the real portal does."""
import os
import sys
import tempfile

from jeepney import DBusAddress, new_method_return, new_signal, MessageType, HeaderFields
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection


def main():
    conn = open_dbus_connection(bus="SESSION", enable_fds=True)
    conn.send_and_get_reply(message_bus.RequestName("org.freedesktop.portal.Desktop"))
    print("ready", flush=True)
    while True:
        msg = conn.receive()
        if msg.header.message_type != MessageType.method_call:
            continue
        member = msg.header.fields.get(HeaderFields.member)
        sender = msg.header.fields.get(HeaderFields.sender)[1:].replace(".", "_")  # HeaderFields.sender
        body = msg.body
        if member == "OpenPipeWireRemote":
            r, w = os.pipe()
            conn.send(new_method_return(msg, "h", (r,)))
            continue
        opts = body[-1]
        token = opts["handle_token"][1]
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        conn.send(new_method_return(msg, "o", (path,)))
        if member == "CreateSession":
            res = {"session_handle": ("s", "/org/freedesktop/portal/desktop/session/x/" + opts["session_handle_token"][1])}
        elif member == "SelectSources":
            assert opts["persist_mode"][1] == 2
            res = {}
        elif member == "Start":
            res = {"streams": ("a(ua{sv})", [(42, {"size": ("(ii)", (1920, 1080))})]),
                   "restore_token": ("s", "tok123")}
        elif member == "Screenshot":
            import numpy as np, cv2
            f = tempfile.mktemp(suffix=".png")
            cv2.imwrite(f, np.full((10, 20, 3), 128, np.uint8))
            res = {"uri": ("s", "file://" + f)}
        else:
            res = {}
        sig = new_signal(DBusAddress(path, interface="org.freedesktop.portal.Request"), "Response",
                         "ua{sv}", (0, res))
        conn.send(sig)


if __name__ == "__main__":
    main()
