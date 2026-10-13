# -*- coding: utf-8 -*-
# MultiBootStartupMenu - boot menu for the Vu+ kexec MultiBoot (OpenBH)
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only

from Plugins.Plugin import PluginDescriptor

from . import _


def main(session, close=None, **kwargs):
	from .ui import MultiBootStartupMenuSetup
	session.open(MultiBootStartupMenuSetup)


def menu(menuid, **kwargs):
	if menuid == "shutdown":
		from .glue import is_available
		if is_available():
			return [(_("MultiBoot startup menu setup"), main, "multiboot_startup_menu", 50)]
	return []


def sessionstart(reason, session=None, **kwargs):
	if reason != 0 or session is None:
		return
	try:
		from .glue import on_session_start
		on_session_start(session)
	except Exception:
		import traceback
		traceback.print_exc()


def Plugins(**kwargs):
	# The Recovery is where you end up when something goes wrong: the plugin
	# stays out of it. Everywhere else the decision is is_available(), which
	# looks at the boot partition rather than at the name of the receiver.
	#
	# When the answer is no, nothing else of the plugin will ever run - not
	# even the session-start hook, which is registered below. So the one line
	# saying why has to be written here: on a receiver where the plugin does
	# not appear, it is the only thing there is to report.
	from Components.SystemInfo import SystemInfo
	if SystemInfo.get("MultiBootSlot") == 0:
		return []
	from .glue import is_available, why_not_available
	if not is_available():
		print("[MultiBootStartupMenu] not active here: %s" % why_not_available())
		return []
	return [
		PluginDescriptor(name=_("MultiBoot startup menu setup"), description=_("Choose the image to start at every power-on"), where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main),
		PluginDescriptor(name=_("MultiBoot startup menu setup"), description=_("Choose the image to start at every power-on"), where=PluginDescriptor.WHERE_MENU, fnc=menu),
		PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart),
	]
