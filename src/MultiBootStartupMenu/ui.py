# -*- coding: utf-8 -*-
# MultiBootStartupMenu - setup, wait and preview screens
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# Dialogs and the exec context
# ---------------------------
# enigma2 refuses to open a modal dialog while the session is not "in exec":
#
#     def open(self, screen, *arguments, **kwargs):
#         if self.dialog_stack and not self.in_exec:
#             raise RuntimeError("[StartEnigma] Error: Modal open are allowed
#                                 only from a screen which is modal!")
#
# in_exec is True during normal operation (key handlers, timer callbacks), but
# Session.close() sets it to False and only the deferred pop of the closed
# dialog (delay_timer -> popCurrent -> execBegin) sets it back. Opening a
# dialog right after closing another one therefore raises - that was the crash
# of 0.1.0, and 0.2.0 avoided it by queueing everything through
# Tools.Notifications, which made the messages appear only after leaving every
# menu. 0.3.0 opens them directly instead, with openLater(): it checks the
# same condition enigma2 checks and, if the session is in that short window,
# retries a few milliseconds later. No queue, no guessing.

import os

from enigma import eTimer, getDesktop

from Components.ActionMap import ActionMap
from Components.config import ConfigSelection, ConfigYesNo, NoSave
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import QUIT_REBOOT, TryQuitMainloop

from . import _
from .core import TIMEOUTS, DEFAULT_TIMEOUT, BootEnv, BootMenuError
from .glue import (collect_entries, current_slot, default_index, is_available, menu_strings,
	model_name, output_settings, render_frames, render_preview, run_in_thread)

PREVIEW = "/tmp/multibootstartupmenu_preview.png"
OPEN_RETRY = 50      # ms between two attempts to open a dialog
OPEN_TRIES = 80      # give up after 4 s and fall back to Notifications
WATCHDOG = 180000    # ms: close the wait box even if the job never answers
DECODE_WAIT = 6000   # ms: ePicLoad is asynchronous and may never answer


def log(text):
	print("[MultiBootStartupMenu] %s" % text)


def LoadPixmap_(path):
	"""Tools.LoadPixmap, or loadPNG directly if that module is not there."""
	try:
		from Tools.LoadPixmap import LoadPixmap
		return LoadPixmap(path)
	except Exception as err:
		log("preview: Tools.LoadPixmap unusable (%s), trying loadPNG" % err)
	try:
		from enigma import loadPNG
		return loadPNG(path)
	except Exception as err:
		log("preview: loadPNG unusable: %s" % err)
		return None


def framebuffer_scale():
	"""The name of this object moved around between enigma2 versions."""
	for attr in ("AVSwitch", "iAVSwitch"):
		try:
			obj = getattr(__import__("Components.AVSwitch", fromlist=[attr]), attr)
			scale = obj().getFramebufferScale() if isinstance(obj, type) else obj.getFramebufferScale()
			if scale and len(scale) == 2:
				return scale
		except Exception:
			continue
	return (1, 1)


class MultiBootStartupMenuWait(Screen):
	"""Modal 'please wait' box with no keys: it is closed by the plugin only.

	A MessageBox would let the user dismiss it while the rendering thread is
	still running; this one ignores every key, so the plugin always knows
	which dialog is on top when it closes it."""

	def __init__(self, session, text):
		width, height = 1000, 180
		size = getDesktop(0).size()
		x = max(0, (size.width() - width) // 2)
		y = max(0, (size.height() - height) // 2)
		self.skin = """<screen name="MultiBootStartupMenuWait" position="%d,%d" size="%d,%d" flags="wfNoBorder" backgroundColor="#00203040">
	<eLabel position="0,0" size="%d,5" backgroundColor="#00296cde" />
	<widget name="text" position="40,5" size="%d,%d" font="Regular;32" halign="center" valign="center" transparent="1" foregroundColor="#00ffffff" />
</screen>""" % (x, y, width, height, width, width - 80, height - 5)
		Screen.__init__(self, session)
		self["text"] = Label(text)
		ignore = {name: self.ignore for name in ("ok", "cancel", "save", "menu", "red", "green", "yellow", "blue")}
		self["actions"] = ActionMap(["SetupActions", "ColorActions", "OkCancelActions"], ignore, -1)

	def ignore(self):
		pass


class MultiBootStartupMenuPreview(Screen):
	"""Full screen picture of the menu.

	The image is put on screen with LoadPixmap, which is synchronous and is
	what every enigma2 plugin uses to show a PNG. ePicLoad is only a fallback:
	it decodes in the background and answers through a callback, and its
	setPara() wants a *list* - a tuple is silently ignored in enigma2, which
	leaves the decoder with a size of 0x0 and the screen black. If neither
	works the screen closes with the reason instead of showing nothing."""

	def __init__(self, session, path):
		size = getDesktop(0).size()
		w, h = size.width(), size.height()
		self.skin = """<screen name="MultiBootStartupMenuPreview" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="#00000000">
	<widget name="preview" position="0,0" size="%d,%d" zPosition="1" alphatest="off" />
</screen>""" % (w, h, w, h)
		Screen.__init__(self, session)
		self.path = path
		self.picload = None
		self.shown_pic = False
		self["preview"] = Pixmap()
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
			"ok": self.leave,
			"cancel": self.leave,
			"red": self.leave,
			"green": self.leave,
			"yellow": self.leave,
			"blue": self.leave,
		}, -1)
		self.decodeTimer = eTimer()
		self.decodeTimer.callback.append(self.decodeTimeout)
		self.onLayoutFinish.append(self.layoutFinished)

	def leave(self, reason=None):
		self.decodeTimer.stop()
		self.close(reason)

	def layoutFinished(self):
		instance = self["preview"].instance
		if instance is None:
			self.leave("the preview widget was not created (skin problem)")
			return
		try:
			instance.setScale(1)  # scale the picture to the widget, if supported
		except Exception:
			pass
		if not os.path.isfile(self.path):
			self.leave("%s is missing" % self.path)
			return
		if self.setPixmap(LoadPixmap_(self.path), "LoadPixmap"):
			return
		self.decode(instance)

	def setPixmap(self, ptr, how):
		"""Some enigma2 versions want the pointer, others the dereferenced
		pixmap: try both rather than guess."""
		if ptr is None:
			log("preview: %s gave nothing" % how)
			return False
		instance = self["preview"].instance
		candidates = [ptr]
		try:
			candidates.append(ptr.__deref__())
		except Exception:
			pass
		last = "no usable pixmap"
		for pixmap in candidates:
			try:
				instance.setPixmap(pixmap)
				self.shown_pic = True
				log("preview: shown with %s" % how)
				return True
			except Exception as err:
				last = err
		log("preview: %s could not be put on screen: %s" % (how, last))
		return False

	# --- fallback: the asynchronous decoder -----------------------------
	def decode(self, instance):
		try:
			from enigma import ePicLoad
			self.picload = ePicLoad()
			self.picload.PictureData.get().append(self.decoded)
			size = instance.size()
			scale = framebuffer_scale()
			# a list, not a tuple: enigma2 checks PyList_Check()
			self.picload.setPara([size.width(), size.height(), scale[0], scale[1], 0, 1, "#00000000"])
			result = self.picload.startDecode(self.path)
			log("preview: ePicLoad.startDecode -> %s" % result)
			if result:
				self.leave("the picture decoder refused %s (error %s)" % (self.path, result))
				return
			self.decodeTimer.start(DECODE_WAIT, True)
		except Exception as err:
			log("preview: ePicLoad failed: %s" % err)
			self.leave(str(err))

	def decoded(self, picInfo=""):
		self.decodeTimer.stop()
		if not self.setPixmap(self.picload.getData(), "ePicLoad"):
			self.leave("the picture could not be decoded")

	def decodeTimeout(self):
		if not self.shown_pic:
			self.leave("the picture decoder did not answer")


class MultiBootStartupMenuSetup(Setup):
	def __init__(self, session, *args, **kwargs):
		self.env = BootEnv()
		self.conf = self.env.read_conf()
		self.available = is_available()
		self.entries = []
		self.entriesError = None
		self.waitBox = None
		self.busy = False
		self.saved = False
		self.pending = None
		self.openTries = 0
		if self.available:
			try:
				self.entries = collect_entries(True)
			except Exception as err:
				self.entriesError = str(err)
		try:
			timeout = int(self.conf.get("TIMEOUT", DEFAULT_TIMEOUT))
		except ValueError:
			timeout = DEFAULT_TIMEOUT
		timeout = min(TIMEOUTS, key=lambda t: abs(t - timeout))
		self.cfgEnabled = NoSave(ConfigYesNo(default=self.conf.get("ENABLED") == "1"))
		self.cfgTimeout = NoSave(ConfigSelection(default=str(timeout), choices=[(str(t), _("%d seconds") % t) for t in TIMEOUTS]))
		self.cfgRecovery = NoSave(ConfigYesNo(default=self.conf.get("SHOWRECOVERY", "1") == "1"))
		defaults = self.defaultChoices()
		default = self.conf.get("DEFAULT", "last")
		if default not in [key for key, text in defaults]:
			default = "last"
		self.cfgDefault = NoSave(ConfigSelection(default=default, choices=defaults))
		Setup.__init__(self, session, setup=None)
		self.setTitle(_("MultiBoot startup menu setup"))
		# The preview is bound here rather than through the yellow_button
		# argument of Setup, which not every image honours.
		self["mbsmColorActions"] = ActionMap(["ColorActions"], {"blue": self.keyPreview}, -1)
		try:
			if "key_blue" not in self:
				from Components.Sources.StaticText import StaticText
				self["key_blue"] = StaticText(_("Preview"))
			elif hasattr(self["key_blue"], "setText"):
				self["key_blue"].setText(_("Preview"))
		except Exception as err:
			log("key_blue: %s" % err)
		self.openTimer = eTimer()
		self.openTimer.callback.append(self.tryOpen)
		self.watchdog = eTimer()
		self.watchdog.callback.append(self.jobTimeout)
		self.onClose.append(self.cleanUp)

	def cleanUp(self):
		for timer in (self.openTimer, self.watchdog):
			try:
				timer.stop()
			except Exception:
				pass

	def recoveryEntry(self):
		for entry in self.entries:
			if entry["slot"] == 0:
				return entry
		return None

	def defaultChoices(self):
		"""The Recovery can be the default image too, but only while it is in
		the menu: an image that is not shown cannot be highlighted."""
		choices = [("last", _("Last started image"))]
		for entry in self.entries:
			if entry["slot"] >= 1 or self.cfgRecovery.value:
				choices.append((str(entry["slot"]), "%s – %s" % (entry["label"], entry["name"])))
		return choices

	def updateDefaultChoices(self):
		choices = self.defaultChoices()
		current = self.cfgDefault.value
		try:
			self.cfgDefault.setChoices(choices, default="last")
		except Exception as err:
			log("default image choices: %s" % err)
			return
		self.cfgDefault.value = current if current in [key for key, text in choices] else "last"

	def recoveryText(self):
		entry = self.recoveryEntry()
		if entry:
			return _("Adds the Recovery image (slot 0) as the first entry of the list, and lets you choose it as the default image.\nFound: %s") % entry["name"]
		return _("No Recovery image was found in the boot partition (STARTUP_RECOVERY or the image itself is missing), so it cannot be added to the menu.")

	def createSetup(self, *args, **kwargs):
		items = [(_("Show the boot menu at startup"), self.cfgEnabled, self.stateText())]
		if self.cfgEnabled.value:
			self.updateDefaultChoices()
			items.append((_("Automatic start after"), self.cfgTimeout, _("If no key is pressed, the highlighted image starts automatically after this time.")))
			items.append((_("Default image"), self.cfgDefault, _("The image highlighted when the menu appears. 'Last started image' follows your last choice.")))
			items.append((_("Show the Recovery in the menu"), self.cfgRecovery, self.recoveryText()))
		self.list = items
		self["config"].list = items

	def stateText(self):
		text = _("When enabled, the receiver shows the list of the MultiBoot slots at every start and lets you choose with the remote control.")
		if not self.available:
			return _("This receiver is not supported by this version of the boot menu.")
		if self.conf.get("ENABLED") == "1":
			state = _("active") if self.env.startup_is_menu() else _("active (STARTUP changed by another image: it will be restored)")
		else:
			state = _("not active")
		return "%s\n%s" % (text, _("Current state: %s") % state)

	# ------------------------------------------------------------------
	# opening dialogs
	def canOpen(self):
		"""The exact condition enigma2 uses in Session.open()."""
		try:
			return not self.session.dialog_stack or self.session.in_exec
		except AttributeError:  # a fork without those attributes: just try
			return True

	def openLater(self, screen, *args, **kwargs):
		"""Open screen as soon as the session accepts a modal dialog."""
		self.pending = (kwargs.pop("callback", None), screen, args, kwargs)
		self.openTries = 0
		self.tryOpen()

	def tryOpen(self):
		if self.pending is None:
			return
		if self.canOpen():
			callback, screen, args, kwargs = self.pending
			self.pending = None
			if callback is None:
				self.session.open(screen, *args, **kwargs)
			else:
				self.session.openWithCallback(callback, screen, *args, **kwargs)
			return
		self.openTries += 1
		if self.openTries > OPEN_TRIES:
			callback, screen, args, kwargs = self.pending
			self.pending = None
			print("[MultiBootStartupMenu] the session never accepted the dialog: queued instead")
			from Tools import Notifications
			if callback is None:
				Notifications.AddNotification(screen, *args, **kwargs)
			else:
				Notifications.AddNotificationWithCallback(callback, screen, *args, **kwargs)
			return
		self.openTimer.start(OPEN_RETRY, True)

	def error(self, text):
		self.openLater(MessageBox, text, MessageBox.TYPE_ERROR)

	# ------------------------------------------------------------------
	# wait box
	def showWait(self, text):
		self.busy = True
		self.watchdog.start(WATCHDOG, True)
		self.waitBox = self.session.open(MultiBootStartupMenuWait, text)

	def hideWait(self):
		self.busy = False
		self.watchdog.stop()
		box, self.waitBox = self.waitBox, None
		if box is not None:
			try:
				box.close()
			except Exception as err:  # it was not on top any more
				print("[MultiBootStartupMenu] wait box: %s" % err)

	def jobTimeout(self):
		if not self.busy:
			return
		self.hideWait()
		self.error(_("The boot menu did not answer in time. Look at the log for details."))

	# ------------------------------------------------------------------
	def menuEntries(self):
		return [e for e in self.entries if e["slot"] >= 1 or self.cfgRecovery.value]

	def settings(self):
		return {
			"TIMEOUT": self.cfgTimeout.value,
			"DEFAULT": self.cfgDefault.value,
			"SHOWRECOVERY": "1" if self.cfgRecovery.value else "0",
		}

	def checkReady(self):
		if not self.available:
			self.error(_("This receiver is not supported by this version of the boot menu."))
			return None
		entries = self.menuEntries()
		if not [e for e in entries if e["slot"] >= 1]:
			self.error(_("No bootable image found.") + ("\n" + self.entriesError if self.entriesError else ""))
			return None
		try:
			import PIL  # noqa: F401
		except ImportError:
			self.error(_("The Python imaging library (PIL) is missing."))
			return None
		return entries

	# ------------------------------------------------------------------
	# GREEN: save
	def keySave(self):
		if self.busy:  # the frames are being rendered: ignore a second save
			return
		if self.cfgEnabled.value:
			entries = self.checkReady()
			if entries is None:
				return
			settings = self.settings()
			settings.update(output_settings())
			slot = current_slot()
			if slot and slot >= 1:
				settings["LAST"] = str(slot)
			env = self.env
			timeout = int(self.cfgTimeout.value)
			strings = menu_strings()
			model = model_name()

			def job():
				render_frames(env, entries, timeout, strings, model)
				return env.enable(settings)

			self.showWait(_("Preparing the boot menu, please wait..."))
			run_in_thread(job, self.enableReady)
		elif self.conf.get("ENABLED") == "1":
			try:
				target = self.disableTarget()
				self.env.disable(target, self.settings())
			except (OSError, BootMenuError) as err:
				self.error(_("The boot menu could not be disabled:\n%s") % err)
				return
			self.conf = self.env.read_conf()
			self.saved = True
			self.openLater(MessageBox, _("The boot menu has been disabled: the receiver will start slot %d directly.") % target,
				MessageBox.TYPE_INFO, timeout=10, callback=self.closeScreen)
		else:
			self.close()

	def enableReady(self, result, error):
		"""Runs from the polling timer of run_in_thread. Closing the wait box
		makes the session leave the exec context for a moment, so the next
		dialog goes through openLater()."""
		self.hideWait()
		if error:
			self.error(_("The boot menu could not be enabled:\n%s") % error)
			return
		self.conf = self.env.read_conf()
		self.saved = True
		self.openLater(MessageBox, _("The boot menu is active and will appear at the next start of the receiver.\n\nRestart now to try it?"),
			MessageBox.TYPE_YESNO, default=False, callback=self.rebootAnswer)

	def rebootAnswer(self, answer):
		if answer:
			self.openLater(TryQuitMainloop, QUIT_REBOOT)
			return
		self.close()

	def closeScreen(self, *args):
		self.close()

	def disableTarget(self):
		slots = self.env.startup_slots()
		candidates = [self.cfgDefault.value, current_slot(), self.conf.get("LAST")]
		for candidate in candidates:
			try:
				slot = int(candidate)
			except (TypeError, ValueError):
				continue
			if slot in slots:
				return slot
		if slots:
			return slots[0]
		raise BootMenuError("no STARTUP_n file found")

	# ------------------------------------------------------------------
	# RED: leave, after one confirmation and nothing else
	def keyCancel(self):
		if self.busy:
			return
		if self.saved or not self.isChanged():
			text = _("Leave the boot menu settings?")
		else:
			text = _("The changes have not been saved.\nLeave anyway?")
		self.openLater(MessageBox, text, MessageBox.TYPE_YESNO, default=False, callback=self.cancelAnswer)

	keyExit = keyCancel

	def isChanged(self):
		try:
			return bool(self["config"].isChanged())
		except Exception:
			return (self.cfgEnabled.value != (self.conf.get("ENABLED") == "1")
				or self.cfgTimeout.value != str(self.conf.get("TIMEOUT"))
				or self.cfgDefault.value != self.conf.get("DEFAULT")
				or self.cfgRecovery.value != (self.conf.get("SHOWRECOVERY", "1") == "1"))

	def cancelAnswer(self, answer):
		if answer:
			self.close()

	# ------------------------------------------------------------------
	# YELLOW: preview
	def keyPreview(self):
		if self.busy:
			return
		entries = self.checkReady()
		if entries is None:
			return
		index = default_index(entries, self.cfgDefault.value, current_slot() or self.conf.get("LAST"))
		timeout = int(self.cfgTimeout.value)
		size = getDesktop(0).size()
		screen = (size.width(), size.height())
		self.showWait(_("Preparing the preview, please wait..."))
		run_in_thread(lambda: render_preview(entries, timeout, PREVIEW, index, screen), self.previewReady)

	def previewReady(self, result, error):
		self.hideWait()
		if error:
			self.error(str(error))
			return
		self.openLater(MultiBootStartupMenuPreview, result, callback=self.previewClosed)

	def previewClosed(self, reason=None):
		# the preview reports why it could not show the picture instead of
		# leaving a black screen
		if reason:
			self.error(_("The preview could not be shown:\n%s") % reason)
