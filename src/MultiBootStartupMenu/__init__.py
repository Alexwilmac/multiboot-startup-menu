# -*- coding: utf-8 -*-
# MultiBootStartupMenu - translations
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
import gettext

from Components.Language import language
from Tools.Directories import SCOPE_PLUGINS, resolveFilename

PluginLanguageDomain = "MultiBootStartupMenu"
PluginLanguagePath = "SystemPlugins/MultiBootStartupMenu/locale"


def localeInit():
	gettext.bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	translated = gettext.dgettext(PluginLanguageDomain, txt)
	if translated == txt:
		import builtins
		enigma2 = getattr(builtins, "_", None)
		if enigma2 is not None and enigma2 is not _:
			translated = enigma2(txt)
	return translated


def e2_(txt):
	"""Translation in the enigma2 domain (to compare with strings of the image)."""
	import builtins
	enigma2 = getattr(builtins, "_", None)
	return enigma2(txt) if enigma2 is not None else txt


localeInit()
language.addCallback(localeInit)
