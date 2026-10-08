# -*- coding: utf-8 -*-
# MultiBootStartupMenu - link between enigma2 and core.py / render.py
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only

import hashlib
import os
import shutil
import threading

from Components.SystemInfo import SystemInfo

from . import _, e2_
from . import core
from .core import BootEnv, BootMenuError, SUPPORTED_MODELS, VERSION, fsync_dir, slot_startup_name

try:
	from Components.SystemInfo import MODEL
except ImportError:
	MODEL = ""


def is_available():
	return bool(SystemInfo.get("HasKexecMultiboot")) and MODEL in SUPPORTED_MODELS and BootEnv().is_kexec_layout()


def current_slot():
	slot = SystemInfo.get("MultiBootSlot")
	return slot if isinstance(slot, int) else None


def menu_enabled():
	try:
		return bool(SystemInfo.get("HasKexecMultiboot")) and BootEnv().read_conf().get("ENABLED") == "1"
	except Exception:
		return False


def model_name():
	try:
		from Components.SystemInfo import getBoxDisplayName
		return "%s %s" % getBoxDisplayName()
	except Exception:
		return MODEL


def recovery_name():
	try:
		from Tools.Multiboot import createInfo
		if os.path.isfile(os.path.join(core.BOOT, "usr/lib/enigma.info")):
			name = createInfo(0, imagedir=core.BOOT)
			if name and name.strip():
				return name.strip()
	except Exception as err:
		print("[MultiBootStartupMenu] recovery name: %s" % err)
	return _("Recovery mode")


def has_recovery(env=None):
	"""The Recovery is slot 0: its rootfs IS the root of the boot partition,
	so it is never listed in canMultiBoot (which only has linuxrootfs<n>
	subdirectories). Its presence is decided by STARTUP_RECOVERY plus an
	image at the root of the partition - exactly what the kexec stage boots."""
	env = env or BootEnv()
	if not os.path.isfile(env.path("STARTUP_RECOVERY")):
		return False
	return env.exists("usr/bin/enigma2") or env.exists("sbin/init")


def recovery_entry():
	if not has_recovery():
		return None
	return {"slot": 0, "startup": "STARTUP_RECOVERY", "label": _("Recovery"), "name": recovery_name(), "tag": "eMMC"}


def collect_entries(show_recovery=True):
	"""Bootable slots as shown by the MultiBoot Image Selector, with the
	Recovery first: it is also the image the menu falls back to, and it has to
	be the easiest one to reach."""
	from Tools.Multiboot import GetImagelist
	slots = SystemInfo.get("canMultiBoot") or {}
	images = GetImagelist()
	skip = (e2_("Empty slot"), e2_("Deleted image"))
	entries = []
	recovery = recovery_entry() if show_recovery else None
	if recovery:
		entries.append(recovery)
	for slot in sorted(k for k in slots if isinstance(k, int) and k >= 1):
		name = str(images.get(slot, {}).get("imagename", "")).strip()
		if not name or name in skip:
			continue
		info = slots[slot]
		entries.append({
			"slot": slot,
			"startup": info.get("startupfile") or slot_startup_name(slot),
			"label": _("Slot %d") % slot,
			"name": name,
			"tag": info.get("slotType", "") or "",
		})
	return entries


def menu_strings():
	return {
		"brand": _("VU+ MULTIBOOT"),
		"title": _("Choose the image to start"),
		"count_caption": _("Auto start in"),
		"count_unit": _("s"),
		"idle": _("Press OK to start the highlighted image"),
		"starting": _("Starting %s…"),
		"error": _("This image cannot be started (missing or incomplete)"),
		"hint_move": _("Select"),
		"hint_ok": _("Start"),
		"hint_digits": _("Direct start"),
	}


def read_proc(path):
	try:
		with open(path) as f:
			return f.read().strip()
	except (OSError, UnicodeDecodeError):
		return ""


def output_settings():
	"""Video mode, OSD position/alpha and remote control code of this slot,
	reused by the menu (it runs before any enigma2 has set them)."""
	from Components.config import config
	settings = {"VIDEOMODE": read_proc("/proc/stb/video/videomode"), "OSD": "", "ALPHA": ""}
	code = read_proc("/proc/stb/fp/remote_code")
	settings["RCCODE"] = code if code.isdigit() else ""
	rctype = read_proc("/proc/stb/ir/rc/type")
	settings["RCTYPE"] = rctype if rctype.isdigit() and rctype != "0" else ""
	try:
		settings["OSD"] = "%d,%d,%d,%d" % (int(config.osd.dst_left.value), int(config.osd.dst_width.value), int(config.osd.dst_top.value), int(config.osd.dst_height.value))
	except Exception:
		pass
	try:
		settings["ALPHA"] = str(int(config.osd.alpha.value))
	except Exception:
		pass
	return settings


def fallback_recovery():
	"""The Recovery as a fall-back target, whether or not it is shown in the
	menu: hiding it is a matter of taste, the safety net is not."""
	entry = recovery_entry()
	if not entry:
		return None
	return (entry["startup"], "%s – %s" % (entry["label"], entry["name"]))


def signature(entries, timeout, strings, model, recovery=None):
	text = repr((VERSION, [(e["slot"], e["startup"], e["label"], e["name"], e["tag"]) for e in entries], int(timeout), sorted(strings.items()), model, recovery))
	return hashlib.md5(text.encode("utf-8")).hexdigest()


def render_frames(env, entries, timeout, strings=None, model=None):
	from .render import MenuRenderer
	strings = strings or menu_strings()
	model = model if model is not None else model_name()
	recovery = fallback_recovery()
	sig = signature(entries, timeout, strings, model, recovery)
	new = env.frames + ".new"
	old = env.frames + ".old"
	shutil.rmtree(new, ignore_errors=True)
	MenuRenderer(entries, strings, model, timeout=int(timeout)).write_all(new, int(timeout), sig, recovery)
	shutil.rmtree(old, ignore_errors=True)
	if os.path.isdir(env.frames):
		os.rename(env.frames, old)
	os.rename(new, env.frames)
	shutil.rmtree(old, ignore_errors=True)
	fsync_dir(env.bm)
	return sig


def render_preview(entries, timeout, path, default_index=0, size=None):
	"""size: the OSD size, so the picture needs no scaling on screen."""
	from .render import MenuRenderer
	img = MenuRenderer(entries, menu_strings(), model_name(), timeout=int(timeout)).preview(default_index, int(timeout), size)
	img.save(path)
	return path


def default_index(entries, default, last):
	wanted = str(last) if default == "last" else str(default)
	for i, entry in enumerate(entries):
		if str(entry["slot"]) == wanted:
			return i
	return 0


def version_tuple(text):
	try:
		return tuple(int(x) for x in str(text).split("."))
	except ValueError:
		return (0,)


def refresh_if_needed():
	"""Background job: keep the menu in line with the slots and the plugin."""
	env = BootEnv()
	conf = env.read_conf()
	if conf.get("ENABLED") != "1":
		return "disabled"
	done = []
	installed = version_tuple(conf.get("VERSION"))
	if installed > version_tuple(VERSION):
		return "a newer version (%s) is installed in another slot: nothing done" % conf.get("VERSION")
	newer = installed < version_tuple(VERSION)
	source_changed = env.source_md5() != conf.get("SOURCE_MD5")
	if newer or source_changed:
		md5 = env.install_payload()
		conf = env.update_conf(VERSION=VERSION, INITRD_MD5=md5, SOURCE_MD5=env.source_md5())
		done.append("payload %s" % ("updated" if newer else "rebuilt: STARTUP.cpio.gz changed"))
	try:
		timeout = int(conf.get("TIMEOUT", "10"))
	except ValueError:
		timeout = 10
	entries = collect_entries(conf.get("SHOWRECOVERY") == "1")
	if entries:
		strings = menu_strings()
		model = model_name()
		if signature(entries, timeout, strings, model, fallback_recovery()) != env.frames_signature():
			render_frames(env, entries, timeout, strings, model)
			done.append("frames")
	return ", ".join(done) or "up to date"


def run_in_thread(job, done_callback):
	"""Run job() in a thread; done_callback(result, error) runs in the main thread."""
	from enigma import eTimer
	state = {}

	def worker():
		try:
			state["result"] = job()
		except Exception as err:
			import traceback
			traceback.print_exc()
			state["error"] = err
		state["finished"] = True

	timer = eTimer()

	def poll():
		if state.get("finished"):
			timer.stop()
			state["done"] = True
			done_callback(state.get("result"), state.get("error"))

	timer.callback.append(poll)
	thread = threading.Thread(target=worker, name="MultiBootStartupMenu")
	thread.daemon = True
	thread.start()
	timer.start(250, False)
	state["timer"] = timer  # keep a reference until the callback has run
	run_in_thread.jobs = [j for j in run_in_thread.jobs if not j.get("done")] + [state]


run_in_thread.jobs = []


# ---------------------------------------------------------------------------
# While the menu is enabled, switching slot from OpenBH writes STARTUP_ONCE
# (one boot of that slot) instead of replacing STARTUP, so the menu stays.

def install_patches():
	try:
		from Screens import MultiBootSelector as mbs
		cls = mbs.MultiBootSelector
		if not getattr(cls, "_mbsm_patched", False):
			original = cls.reboot

			def reboot(self):
				if menu_enabled():
					try:
						slot = self["config"].getCurrent()[0][1][0]
						BootEnv().boot_once(slot)
						print("[MultiBootStartupMenu] MultiBootSelector: STARTUP_ONCE <- slot %s" % slot)
						self.cancel(mbs.QUIT_REBOOT)
						return
					except Exception as err:
						print("[MultiBootStartupMenu] MultiBootSelector patch failed, using the original: %s" % err)
				original(self)

			cls.reboot = reboot
			cls._mbsm_patched = True
	except Exception as err:
		print("[MultiBootStartupMenu] cannot patch MultiBootSelector: %s" % err)

	try:
		from Plugins.SystemPlugins.OBH import ImageManager as im
		cls = im.OpenBhImageManager
		if not getattr(cls, "_mbsm_patched", False):
			original_flash = cls.FlashQuestion

			def FlashQuestion(self, answer):
				if answer is True and menu_enabled() and int(getattr(self, "multibootslot", 0) or 0) >= 1:
					try:
						BootEnv().boot_once(int(self.multibootslot))
						print("[MultiBootStartupMenu] ImageManager: STARTUP_ONCE <- slot %s" % self.multibootslot)
						from Screens.Standby import TryQuitMainloop
						self.session.open(TryQuitMainloop, 2)
						return
					except Exception as err:
						print("[MultiBootStartupMenu] ImageManager patch failed, using the original: %s" % err)
				original_flash(self, answer)

			cls.FlashQuestion = FlashQuestion
			cls._mbsm_patched = True
	except Exception as err:
		print("[MultiBootStartupMenu] cannot patch ImageManager: %s" % err)

	try:
		import Tools.Multiboot as tm
		if not getattr(tm, "_mbsm_patched", False):
			original_activate = tm.activateSlot

			def activateSlot(slotCode, bootCode, callback):
				if menu_enabled():
					try:
						BootEnv().boot_once(int(slotCode))
						print("[MultiBootStartupMenu] activateSlot: STARTUP_ONCE <- slot %s" % slotCode)
						callback(0, 0)
						return
					except Exception as err:
						print("[MultiBootStartupMenu] activateSlot patch failed, using the original: %s" % err)
				original_activate(slotCode, bootCode, callback)

			tm.activateSlot = activateSlot
			tm._mbsm_patched = True
	except Exception as err:
		print("[MultiBootStartupMenu] cannot patch activateSlot: %s" % err)


def pending_notice():
	"""Text to show once about a problem of the menu stage, or None."""
	env = BootEnv()
	status = env.status()
	conf = env.read_conf()
	if not status or status.startswith("OK") or conf.get("NOTIFIED") == status:
		return None
	env.update_conf(NOTIFIED=status)
	if status.startswith("DISABLED"):
		return _("The boot menu could not start twice in a row and has been disabled automatically.\nDetails in /boot/bootmenu/bootmenu.log")
	if status.startswith("FAILSAFE"):
		return _("The boot menu could not start at the last boot: the default image was started instead.\nDetails in /boot/bootmenu/bootmenu.log")
	if status.startswith("NEVER_RAN"):
		return _("The boot menu never started since it was activated and STARTUP was changed in the meantime: it has been disabled for safety. You can enable it again from the plugin.")
	if status.startswith("WRAPPER_FAILED"):
		return _("The boot menu was skipped at the last boot and the Recovery was started.\nDetails in /boot/bootmenu/status and bootmenu.log")
	return None


def on_session_start(session):
	if not is_available():
		return
	install_patches()
	env = BootEnv()
	try:
		action = env.on_session_start(current_slot())
		if action:
			print("[MultiBootStartupMenu] STARTUP %s" % action)
	except (OSError, BootMenuError) as err:
		print("[MultiBootStartupMenu] session start: %s" % err)
	try:
		notice = pending_notice()
		if notice:
			from Screens.MessageBox import MessageBox
			from Tools import Notifications
			Notifications.AddNotification(MessageBox, notice, MessageBox.TYPE_WARNING, timeout=30)
	except Exception as err:
		print("[MultiBootStartupMenu] notice: %s" % err)
	if env.read_conf().get("ENABLED") == "1":
		from enigma import eTimer

		def later():
			run_in_thread(refresh_if_needed, lambda result, error: print("[MultiBootStartupMenu] refresh: %s" % (error or result)))

		timer = eTimer()
		timer.callback.append(later)
		timer.start(60000, True)
		on_session_start.timer = timer
