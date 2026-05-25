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


_BAR_WIDTH = 80   # narrow enough that a title embedded in the bar doesn't wrap
                  # in the Indigo log viewer (letters render fractionally wider
                  # than '=', so 110-wide bars hit the wrap point on the title row)


def log_startup_banner(plugin_id, display_name, version, extras=None):
    """
    Print a multi-line banner using raw indigo.server.log (no timestamp prefix
    from any logging filter) so the banner stays clean and easy to spot.

    The title is embedded INSIDE a single bar line (rather than centred on a
    separate row between two bars) so the visual centring doesn't depend on
    spaces and '=' characters rendering at identical widths — they don't
    always, in the Indigo client's log viewer font. By making the padding on
    each side of the title from the same character as the bar itself, the
    title is unambiguously sat in the middle of the bar regardless of font.
    """
    title = f" {display_name} v{version} "
    pad = max(0, _BAR_WIDTH - len(title))
    left = pad // 2
    right = pad - left
    title_bar = ("=" * left) + title + ("=" * right)
    plain_bar = "=" * _BAR_WIDTH

    indigo.server.log(plain_bar)
    indigo.server.log(title_bar)
    indigo.server.log(plain_bar)
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
    indigo.server.log(plain_bar)
