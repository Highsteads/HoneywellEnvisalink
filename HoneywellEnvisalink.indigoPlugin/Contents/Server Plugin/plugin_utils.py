#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_utils.py
# Description: Shared startup-banner utility — bundled with every Highsteads plugin
#              so we get a consistent, version-prominent banner at plugin start
#              and on demand via the Show Plugin Info menu.
# Author:      Highsteads / CliveS
# Date:        24-05-2026
# Version:     1.0

import indigo
import platform
import sys


_BAR_WIDTH = 110


def log_startup_banner(plugin_id, display_name, version, extras=None):
    """
    Print a multi-line banner using raw indigo.server.log (no timestamp prefix
    from any logging filter) so the banner stays clean and easy to spot.

    Uses ASCII '=' for the bar (not the Unicode '═' box-drawing char) so the
    bar and the centred title row are guaranteed the same visual width in
    every terminal / font — '═' renders fractionally wider than a space in
    several common monospace fonts, which throws the centring off visually.
    """
    title = f"{display_name} v{version}"
    bar = "=" * _BAR_WIDTH
    centred = title.center(_BAR_WIDTH)

    indigo.server.log(bar)
    indigo.server.log(centred)
    indigo.server.log(bar)
    indigo.server.log(f"  Plugin ID       : {plugin_id}")
    indigo.server.log(f"  Plugin version  : {version}")
    indigo.server.log(f"  Indigo version  : {indigo.server.version}")
    indigo.server.log(f"  API version     : {indigo.server.apiVersion}")
    indigo.server.log(f"  Python          : {sys.version.split()[0]} ({platform.machine()})")
    indigo.server.log(f"  macOS           : {platform.mac_ver()[0]}")
    if extras:
        for label, value in extras:
            # Strip any trailing colon from the supplied label, then format with
            # the same column layout as the standard fields above so colons and
            # values line up consistently across the whole banner.
            clean_label = label.rstrip(":").rstrip()
            indigo.server.log(f"  {clean_label:15s} : {value}")
    indigo.server.log(bar)
