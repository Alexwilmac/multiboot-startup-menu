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
	"""Whether the plugin shows itself at all.

	What the menu depends on is the layout of the boot partition, not the name
	of the receiver, so that is what is asked. Up to 0.5.0 the model had to be
	in SUPPORTED_MODELS as well, which meant that nobody outside the three
	tested receivers could even try: the plugin simply was not there. Now it
	appears, says plainly that this receiver has not been tested, and does
	nothing until the user accepts that - see is_tested()."""
	return BootEnv().is_kexec_layout()


def is_tested():
	"""Whether this receiver is one of those the menu has been seen to work on.
	Everything the user is warned about hangs on this."""
	return MODEL in SUPPORTED_MODELS and bool(SystemInfo.get("HasKexecMultiboot"))


def current_slot():
	slot = SystemInfo.get("MultiBootSlot")
	return slot if isinstance(slot, int) else None


def menu_enabled():
	"""Only the permanent state: during a trial (ENABLED=once) nothing else in
	the image should start behaving differently."""
	try:
		return BootEnv().read_conf().get("ENABLED") == "1"
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


def lcd_size():
	"""The front display of this receiver, read where enigma2 reads it.

	The same panel is there during the boot menu, so unlike the television
	framebuffer there is nothing to discover at boot and record for next time:
	what the running image reports is what the menu stage will find. The
	values in these nodes are hexadecimal. None when the receiver has no
	display the menu could draw on - a few characters of text, or none at
	all - and then the menu simply does not use one."""
	def node(name):
		try:
			with open("/proc/stb/lcd/" + name) as f:
				return int(f.read().strip(), 16)
		except (OSError, ValueError):
			return 0
	from .lcd import usable
	size = (node("xres"), node("yres"))
	return size if usable(size, node("bpp")) else None


def osd_mode(env=None):
	"""native or double: the menu stage puts the framebuffer on the screen at
	its own size, or at exactly twice it, instead of letting the scaler
	stretch it to fill the screen. Empty means the receiver decides, which is
	what every version up to 0.7.8 did."""
	try:
		mode = (env or BootEnv()).read_conf().get("OSDMODE", "").strip().lower()
	except OSError:
		return ""
	return mode if mode in ("native", "double") else ""


def frame_size(env=None):
	"""The framebuffer the menu stage will find at boot, as the menu stage
	itself recorded it the last time it ran.

	Unknown until the menu has run once, and 1920x1080 until then - which is
	what every receiver was assumed to have up to 0.7.2, and what made the
	menu look stretched on a Vu+ 4K, whose Recovery comes up at 1920x1440."""
	env = env or BootEnv()
	# With an OSD mode nothing stretches the picture any more, so the frames
	# go back to the plain design size: there is nothing left to compensate.
	if osd_mode(env):
		return (1920, 1080)
	try:
		text = env.read_conf().get("FBNATIVE", "")
		w, h = (int(v) for v in text.lower().split("x", 1))
		if 640 <= w <= 4096 and 480 <= h <= 2304:
			return (w, h)
	except (ValueError, AttributeError):
		pass
	return (1920, 1080)


def signature(entries, timeout, strings, model, recovery=None, size=None, osd="", lcd=None):
	text = repr((VERSION, [(e["slot"], e["startup"], e["label"], e["name"], e["tag"]) for e in entries], int(timeout), sorted(strings.items()), model, recovery, size, osd, lcd))
	return hashlib.md5(text.encode("utf-8")).hexdigest()


def render_frames(env, entries, timeout, strings=None, model=None):
	from .render import MenuRenderer
	strings = strings or menu_strings()
	model = model if model is not None else model_name()
	recovery = fallback_recovery()
	size = frame_size(env)
	lcd = lcd_size()
	sig = signature(entries, timeout, strings, model, recovery, size, osd_mode(env), lcd)
	new = env.frames + ".new"
	old = env.frames + ".old"
	shutil.rmtree(new, ignore_errors=True)
	MenuRenderer(entries, strings, model, timeout=int(timeout), size=size).write_all(new, int(timeout), sig, recovery)
	render_lcd_frames(new, entries, timeout, strings, lcd, recovery)
	shutil.rmtree(old, ignore_errors=True)
	if os.path.isdir(env.frames):
		os.rename(env.frames, old)
	os.rename(new, env.frames)
	shutil.rmtree(old, ignore_errors=True)
	fsync_dir(env.bm)
	return sig


def render_lcd_frames(folder, entries, timeout, strings, size, recovery=None):
	"""The front display frames, beside the television ones, and the line in
	menu.txt that tells the menu stage the panel is there.

	A receiver without a usable front display just does not get them, and the
	menu stage, finding no LCDSIZE line, does not look for them. Nothing here
	may stop the menu being built: a display the plugin cannot draw for is a
	missing convenience, not a failure."""
	if not size:
		return None
	try:
		from .lcd import LcdRenderer
		LcdRenderer(entries, strings, size).write_all(folder, int(timeout), recovery)
	except Exception as err:   # a font, a size, anything: the menu still works
		print("[MultiBootStartupMenu] front display frames not made: %s" % err)
		return None
	with open(os.path.join(folder, "menu.txt"), "a", encoding="utf-8") as f:
		f.write("LCDSIZE=%dx%d\n" % (size[0], size[1]))
	return size


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
		if signature(entries, timeout, strings, model, fallback_recovery(), frame_size(env), osd_mode(env), lcd_size()) != env.frames_signature():
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


TRIAL_NOTICES = {
	"ran": lambda: _("The boot menu was tried once on this receiver and it worked.\n\nYou can now switch it on for good from the plugin: Menu > Standby & Restart > MultiBoot startup menu setup."),
	"menu": lambda: _("The boot menu was tried once on this receiver: it was loaded, but it could not reach the menu and an image was started instead.\nNothing was changed. Details in /boot/bootmenu/bootmenu.log"),
	"initrd": lambda: _("The boot menu was tried once on this receiver and it was not loaded at all: this receiver starts its images in a way the menu cannot hook into.\nNothing was changed."),
}


def trial_notice(outcome):
	maker = TRIAL_NOTICES.get(outcome)
	if not maker:
		return None
	return "%s\n\n%s\n%s" % (maker(), _("If you report this receiver, send a photograph of this line, or the file %s:") % REPORT_FILE, report_line())


REPORT_FILE = "/tmp/receiver-model.txt"


def write_report_file(path=REPORT_FILE):
	"""The report as a file, for whoever would rather copy a file than
	photograph a screen.

	In /tmp because that is the one directory everybody who has ever copied an
	.ipk to a receiver already knows how to reach. /tmp is emptied at every
	start, which is why this is written at every start and not only when the
	plugin is opened: after the reboot of a trial, the file has to be there
	with the result in it."""
	try:
		text = "%s\n\n%s\n" % (report_line(), report())
		with open(path, "w") as f:
			f.write(text)
		return path
	except OSError as err:
		print("[MultiBootStartupMenu] %s: %s" % (path, err))
		return None


def report_line():
	"""Everything a report needs, on one line, so that a photograph of the
	screen is a complete report.

	Most people who install a plugin never open a terminal, and the one thing
	that cannot be guessed from what the screen usually shows is the model
	string: the receiver is called 'Vu+ Duo4K SE' on screen and 'vuduo4kse' in
	the code, and it is the second one that has to go in SUPPORTED_MODELS.
	Left untranslated on purpose: it is meant to be copied or read back, not
	read."""
	try:
		env = BootEnv()
		conf = env.read_conf()
		parts = [
			MODEL or "?",
			image_version(),
			"boot " + ("OK" if env.is_kexec_layout() else "NO"),
			"fb %dx%d" % frame_size(env),
			"tested" if is_tested() else "untested",
		]
		# the code in the boot partition is updated by the plugin, so the two
		# can be a reboot apart: a report naming only one of them is misleading
		installed = conf.get("VERSION")
		if installed and installed != VERSION:
			parts.insert(0, "boot code %s" % installed)
		trial = conf.get("TRIAL")
		if trial:
			parts.append("trial " + trial)
		return "MBSM %s | %s" % (VERSION, " | ".join(parts))
	except Exception as err:
		return "MBSM %s | %s | %s" % (VERSION, MODEL or "?", err)


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


def why_not_available():
	"""One line in the log when the plugin keeps out of the way, so that a
	user can report what was actually missing instead of just 'it does not
	appear'."""
	try:
		env = BootEnv()
		missing = [n for n in ("STARTUP", "STARTUP_RECOVERY", "STARTUP.cpio.gz", "zImage") if not os.path.isfile(env.path(n))]
		return "model=%r, kexec multiboot=%s, missing in %s: %s" % (
			MODEL, bool(SystemInfo.get("HasKexecMultiboot")), env.boot, ", ".join(missing) or "nothing")
	except Exception as err:
		return "could not be determined: %s" % err


def report():
	"""The facts a tester on an untested receiver has to send back. Deliberately
	plain text and no judgement: what is here is what was read."""
	env = BootEnv()
	conf = env.read_conf()
	lines = [
		"MultiBootStartupMenu %s" % VERSION,
		"model: %s (%s)" % (MODEL, model_name()),
		"tested receiver: %s" % ("yes" if is_tested() else "NO"),
		"image: %s" % image_version(),
		"HasKexecMultiboot: %s" % SystemInfo.get("HasKexecMultiboot"),
		"MultiBootSlot: %s" % SystemInfo.get("MultiBootSlot"),
		"canMultiBoot: %s" % sorted(k for k in (SystemInfo.get("canMultiBoot") or {}) if isinstance(k, int)),
		"boot layout complete: %s" % env.is_kexec_layout(),
		"Recovery problems (strict): %s" % ("; ".join(env.recovery_problems(True)) or "none"),
		"Recovery problems (minimum): %s" % ("; ".join(env.recovery_problems(False)) or "none"),
		"Vu+ drivers in the Recovery: %s" % env.has_vuplus_drivers(),
		"STARTUP_n files: %s" % env.startup_slots(),
		"state: ENABLED=%s TRIAL=%s UNTESTED=%s" % (conf.get("ENABLED"), conf.get("TRIAL"), conf.get("UNTESTED")),
		"last menu run: %s" % (env.status() or "never"),
	]
	for name in ("STARTUP", "STARTUP_RECOVERY"):
		try:
			lines.append("%s: %s" % (name, env.read_text(name).strip()))
		except OSError as err:
			lines.append("%s: %s" % (name, err))
	try:
		import PIL
		lines.append("PIL: %s" % getattr(PIL, "__version__", "present"))
	except ImportError:
		lines.append("PIL: MISSING")
	return "\n".join(lines)


def image_version():
	for path, key in (("/etc/os-release", "PRETTY_NAME="), ("/etc/image-version", "version=")):
		try:
			with open(path) as f:
				for line in f:
					if line.startswith(key):
						return line[len(key):].strip().strip('"')
		except OSError:
			continue
	return "unknown"


def on_session_start(session):
	if not is_available():
		print("[MultiBootStartupMenu] not active here: %s" % why_not_available())
		return
	if not is_tested():
		print("[MultiBootStartupMenu] untested receiver, the menu stays off until it is accepted: %s" % why_not_available())
	install_patches()
	env = BootEnv()
	trial = env.read_conf().get("ENABLED") == "once"
	try:
		action = env.on_session_start(current_slot())
		if action:
			print("[MultiBootStartupMenu] STARTUP %s" % action)
	except (OSError, BootMenuError) as err:
		print("[MultiBootStartupMenu] session start: %s" % err)
	# after the trial has been settled, so that the file carries its result
	write_report_file()
	try:
		from Screens.MessageBox import MessageBox
		from Tools import Notifications
		notice = trial_notice(env.read_conf().get("TRIAL")) if trial else pending_notice()
		if trial:
			print("[MultiBootStartupMenu] trial report\n%s" % report())
		if notice:
			Notifications.AddNotification(MessageBox, notice, MessageBox.TYPE_INFO if trial else MessageBox.TYPE_WARNING, timeout=60)
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
