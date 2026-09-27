#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    IndigoSecrets_example.py
# Description: Template for the one setting HoneywellEnvisalink reads from
#              IndigoSecrets.py. Optional: you can type the password in the
#              plugin's Configure dialog instead.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0

# HOW TO USE IT
# Copy this file into:
#     /Library/Application Support/Perceptive Automation/
# and rename the copy to IndigoSecrets.py. If you already have an
# IndigoSecrets.py there (other CliveS plugins use the same file), add the
# line below to it instead of replacing it.
#
# A value set here is used in preference to the one in
# Plugins -> HoneywellEnvisalink -> Configure. Leave it blank to use the dialog.
#
# The plugin reads this file when it starts, so restart the plugin after
# editing it. Never commit IndigoSecrets.py to git.

# Envisalink web password (the EVL's factory default is "user").
ENVISALINK_PASSWORD = ""
