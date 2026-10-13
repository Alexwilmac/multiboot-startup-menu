# -*- coding: utf-8 -*-
# MultiBootStartupMenu - core logic
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# Everything that touches the boot partition lives here. No enigma2 imports,
# so the module can be tested off-box with a fake boot directory.

import gzip
import hashlib
import os
import shutil
import time

VERSION = "0.7.1"
BOOT = "/boot"  # root of the boot partition (Recovery + slots) as mounted in a Vu+ kexec slot
BMNAME = "bootmenu"
INITRD_NAME = "bootmenu.cpio.gz"
INITRD_REL = BMNAME + "/" + INITRD_NAME

# Receivers on which the menu has actually been seen to work. Nothing else in
# the plugin depends on the model - no partition numbers, no fixed paths - so
# adding one is this line plus someone's test.
#
# Since 0.6.0 this list no longer decides whether the plugin appears: what
# decides is the layout of the boot partition (is_kexec_layout), which is what
# the menu really depends on. On a receiver that is not in this list the plugin
# says so, refuses to do anything until the user explicitly accepts, and offers
# "try once", which loads the menu for a single boot without touching STARTUP.
SUPPORTED_MODELS = (
	"vuultimo4k",   # Vu+ Ultimo 4K
	"vusolo4k",     # Vu+ Solo 4K
	"vuduo4kse",    # Vu+ Duo 4K SE
)
TIMEOUTS = (3, 5, 7, 10, 15, 20, 30)
DEFAULT_TIMEOUT = 10
PAYLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload")
WRAPPER_MARK = b"MultiBootStartupMenu - initrd wrapper"
# the same marker under the name the plugin had before 0.4.0: an initrd built
# by that version must still be recognised as already wrapped
OLD_WRAPPER_MARKS = (b"KexecBootMenu - initrd wrapper",)
UNVERIFIED = ".unverified"

# ENABLED: "1" permanently (STARTUP points to the menu), "once" for a trial
# (only STARTUP_ONCE was written, STARTUP is untouched), "0" otherwise.
ENABLED_OFF, ENABLED_ON, ENABLED_ONCE = "0", "1", "once"

CONF_KEYS = ("ENABLED", "TIMEOUT", "DEFAULT", "LAST", "SHOWRECOVERY", "VIDEOMODE", "OSD", "ALPHA", "RCCODE", "RCTYPE", "VERSION", "INITRD_MD5", "SOURCE_MD5", "NOTIFIED", "MODEL", "UNTESTED", "TRIAL")
CONF_DEFAULTS = {
	"ENABLED": "0",
	"TIMEOUT": str(DEFAULT_TIMEOUT),
	"DEFAULT": "last",
	"LAST": "",
	"SHOWRECOVERY": "1",
	"VIDEOMODE": "",
	"OSD": "",
	"ALPHA": "",
	"RCCODE": "",
	"RCTYPE": "",
	"VERSION": "",
	"INITRD_MD5": "",
	"SOURCE_MD5": "",
	"NOTIFIED": "",
	"MODEL": "",
	"UNTESTED": "0",
	"TRIAL": "",
}


class BootMenuError(Exception):
	pass


def atomic_write(path, data, mode=0o644):
	if isinstance(data, str):
		data = data.encode("utf-8")
	tmp = path + ".tmp"
	with open(tmp, "wb") as f:
		f.write(data)
		f.flush()
		os.fsync(f.fileno())
	os.chmod(tmp, mode)
	os.rename(tmp, path)
	fsync_dir(os.path.dirname(path))


def fsync_dir(path):
	try:
		fd = os.open(path or ".", os.O_RDONLY)
		try:
			os.fsync(fd)
		finally:
			os.close(fd)
	except OSError:
		pass


def slot_startup_name(slot):
	return "STARTUP_RECOVERY" if int(slot) == 0 else "STARTUP_%d" % int(slot)


# ---------------------------------------------------------------------------
# cpio "newc" archives (the format of STARTUP.cpio.gz)

CPIO_FIELDS = ("ino", "mode", "uid", "gid", "nlink", "mtime", "filesize", "devmajor", "devminor", "rdevmajor", "rdevminor", "namesize", "check")


def _align4(n):
	return (n + 3) & ~3


def cpio_parse(raw):
	entries = []
	pos = 0
	while True:
		if raw[pos:pos + 6] != b"070701":
			raise BootMenuError("cpio: bad header at offset %d" % pos)
		fields = {}
		for i, name in enumerate(CPIO_FIELDS):
			fields[name] = int(raw[pos + 6 + i * 8:pos + 14 + i * 8], 16)
		namesize = fields["namesize"]
		name = raw[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "surrogateescape")
		data_start = _align4(pos + 110 + namesize)
		data_end = data_start + fields["filesize"]
		if data_end > len(raw):
			raise BootMenuError("cpio: truncated archive")
		pos = _align4(data_end)
		if name == "TRAILER!!!":
			break
		fields["name"] = name
		fields["data"] = raw[data_start:data_end]
		entries.append(fields)
	return entries


def cpio_build(entries):
	out = bytearray()

	def add(fields, name, data):
		encoded = name.encode("utf-8", "surrogateescape") + b"\0"
		header = b"070701"
		for key in CPIO_FIELDS:
			if key == "filesize":
				value = len(data)
			elif key == "namesize":
				value = len(encoded)
			elif key == "check":
				value = 0
			else:
				value = fields.get(key, 0)
			header += b"%08x" % value
		out.extend(header)
		out.extend(encoded)
		out.extend(b"\0" * (_align4(len(out)) - len(out)))
		out.extend(data)
		out.extend(b"\0" * (_align4(len(out)) - len(out)))

	for entry in entries:
		add(entry, entry["name"], entry["data"])
	add({"nlink": 1}, "TRAILER!!!", b"")
	out.extend(b"\0" * ((512 - len(out) % 512) % 512))
	return bytes(out)


def build_initrd(original_gz, wrapper):
	"""Return the boot menu initrd: the box's own STARTUP.cpio.gz with /init
	renamed to /init.stage2 and the wrapper added as the new /init."""
	if WRAPPER_MARK not in wrapper:
		raise BootMenuError("wrapper script is not valid")
	raw = gzip.decompress(original_gz)
	entries = cpio_parse(raw)
	names = [e["name"] for e in entries]
	init_names = [n for n in names if n in ("init", "./init")]
	if len(init_names) != 1:
		raise BootMenuError("STARTUP.cpio.gz: /init not found")
	init_name = init_names[0]
	prefix = "./" if init_name.startswith("./") else ""
	if prefix + "init.stage2" in names:
		raise BootMenuError("STARTUP.cpio.gz already contains init.stage2")
	original_init = None
	for entry in entries:
		if entry["name"] == init_name:
			original_init = entry
	if any(mark in original_init["data"] for mark in (WRAPPER_MARK,) + OLD_WRAPPER_MARKS):
		raise BootMenuError("STARTUP.cpio.gz is already a boot menu initrd")
	if b"switch_root" not in original_init["data"]:
		raise BootMenuError("STARTUP.cpio.gz: unexpected /init")
	if not any(n.endswith("bin/busybox") or n.endswith("bin/busybox.nosuid") for n in names):
		raise BootMenuError("STARTUP.cpio.gz: busybox not found")
	original_init["name"] = prefix + "init.stage2"
	new_init = dict(original_init)
	new_init.update({
		"name": prefix + "init",
		"ino": max(e["ino"] for e in entries) + 1,
		"mode": 0o100755,
		"nlink": 1,
		"mtime": int(time.time()),
		"data": wrapper,
	})
	entries.append(new_init)
	gz = gzip.compress(cpio_build(entries), compresslevel=9, mtime=0)
	verify_initrd(gz, original_gz, wrapper)
	return gz


def verify_initrd(gz, original_gz, wrapper):
	new = cpio_parse(gzip.decompress(gz))
	old = cpio_parse(gzip.decompress(original_gz))
	new_by_name = {e["name"]: e for e in new}
	if len(new) != len(old) + 1:
		raise BootMenuError("initrd check: wrong number of entries")
	for entry in old:
		name = entry["name"]
		if name in ("init", "./init"):
			name = name + ".stage2"
		other = new_by_name.get(name)
		if other is None or other["data"] != entry["data"] or other["mode"] != entry["mode"]:
			raise BootMenuError("initrd check: %s differs" % name)
	init = new_by_name.get("./init") or new_by_name.get("init")
	if init is None or init["data"] != wrapper or init["mode"] != 0o100755:
		raise BootMenuError("initrd check: new /init is wrong")


# ---------------------------------------------------------------------------

class BootEnv:
	def __init__(self, boot=None, payload_dir=None):
		self.boot = boot or BOOT
		self.payload_dir = payload_dir or PAYLOAD_DIR
		boot = self.boot
		self.bm = os.path.join(boot, BMNAME)
		self.conf_path = os.path.join(self.bm, "bootmenu.conf")
		self.frames = os.path.join(self.bm, "frames")

	def path(self, *parts):
		return os.path.join(self.boot, *parts)

	# --- files inside the boot partition -----------------------------------
	def resolve(self, rel, hops=8):
		"""Path of rel inside the boot partition, following symlinks there
		(absolute link targets are relative to the partition, not to /)."""
		current = rel.lstrip("/")
		for _ in range(hops):
			full = self.path(current)
			if not os.path.islink(full):
				return full
			target = os.readlink(full)
			if target.startswith("/"):
				current = target.lstrip("/")
			else:
				current = os.path.normpath(os.path.join(os.path.dirname(current), target))
		return self.path(current)

	def exists(self, rel):
		return os.path.exists(self.resolve(rel))

	def read_bytes(self, rel):
		with open(self.path(rel), "rb") as f:
			return f.read()

	def read_text(self, rel):
		return self.read_bytes(rel).decode("utf-8", "replace")

	# --- configuration ------------------------------------------------------
	def read_conf(self):
		conf = dict(CONF_DEFAULTS)
		try:
			with open(self.conf_path, encoding="utf-8", errors="replace") as f:
				for line in f:
					line = line.strip()
					if line and not line.startswith("#") and "=" in line:
						key, value = line.split("=", 1)
						conf[key.strip()] = value.strip()
		except (OSError, UnicodeDecodeError):
			pass
		return conf

	def write_conf(self, conf):
		os.makedirs(self.bm, exist_ok=True)
		lines = ["# MultiBootStartupMenu - shared by all slots, read by the boot menu at startup"]
		for key in CONF_KEYS:
			value = str(conf.get(key, CONF_DEFAULTS.get(key, ""))).replace("\n", " ").strip()
			lines.append("%s=%s" % (key, value))
		atomic_write(self.conf_path, "\n".join(lines) + "\n")

	def update_conf(self, **values):
		conf = self.read_conf()
		conf.update({k: str(v) for k, v in values.items()})
		self.write_conf(conf)
		return conf

	def status(self):
		try:
			return self.read_text(os.path.join(BMNAME, "status")).strip()
		except OSError:
			return ""

	# --- STARTUP files --------------------------------------------------------
	def is_kexec_layout(self):
		return all(os.path.isfile(self.path(n)) for n in ("STARTUP", "STARTUP_RECOVERY", "STARTUP.cpio.gz", "zImage"))

	def startup_slots(self):
		slots = []
		try:
			names = os.listdir(self.boot)
		except OSError:
			return slots
		for name in names:
			if name.startswith("STARTUP_") and name[8:].isdigit():
				slots.append(int(name[8:]))
		return sorted(slots)

	def menu_line(self):
		base = self.read_text("STARTUP_RECOVERY").split()
		if not any(t.startswith("kernel=") for t in base) or not any(t.startswith("root=") for t in base):
			raise BootMenuError("STARTUP_RECOVERY is not valid")
		base = [t for t in base if not t.startswith("initrd=")]
		return " ".join(base + ["initrd=" + INITRD_REL])

	def startup_is_menu(self):
		try:
			return ("initrd=" + INITRD_REL) in self.read_text("STARTUP").split()
		except OSError:
			return False

	def set_startup_menu(self):
		atomic_write(self.path("STARTUP"), self.menu_line())
		if not self.startup_is_menu():
			raise BootMenuError("STARTUP could not be written")

	def set_startup_slot(self, slot):
		data = self.read_bytes(slot_startup_name(slot))
		if b"kernel=" not in data:
			raise BootMenuError("%s is not valid" % slot_startup_name(slot))
		atomic_write(self.path("STARTUP"), data)

	def boot_once(self, slot):
		name = slot_startup_name(slot)
		data = self.read_bytes(name)
		if b"kernel=" not in data:
			raise BootMenuError("%s is not valid" % name)
		atomic_write(self.path("STARTUP_ONCE"), data)
		if int(slot) >= 1:
			self.update_conf(LAST=int(slot))

	# --- checks -------------------------------------------------------------
	def recovery_problems(self, strict=True):
		"""What would stop the menu stage from running inside the Recovery.

		The missing-file checks are hard everywhere: without a shell and a
		python3 in the boot partition the menu cannot run at all. The driver
		check is Vu+ specific, so on a receiver outside the tested list it is
		only a warning: another brand brings its framebuffer up its own way,
		and that is one of the things a test is for. If it does not come up,
		the menu stage gives up by itself and the fail-safe starts an image."""
		problems = []
		for rel in ("zImage", "STARTUP.cpio.gz", "STARTUP_RECOVERY", "bin/sh", "usr/bin/python3"):
			if not self.exists(rel):
				problems.append("Recovery: %s missing" % rel)
		if strict and not self.has_vuplus_drivers():
			problems.append("Recovery: Vu+ drivers (vuplus-platform-util) missing")
		return problems

	def has_vuplus_drivers(self):
		if self.exists("etc/init.d/vuplus-platform-util"):
			return True
		try:
			for kver in os.listdir(self.path("lib/modules")):
				if os.path.isfile(self.path("lib/modules", kver, "extra", "brcmfb.ko")):
					return True
		except OSError:
			pass
		return False

	def installation_problems(self, conf=None):
		conf = conf or self.read_conf()
		problems = []
		for name in ("menu-init", "runner.py", INITRD_NAME):
			if not os.path.isfile(os.path.join(self.bm, name)):
				problems.append("%s missing" % name)
		if not os.path.isfile(os.path.join(self.frames, "menu.txt")):
			problems.append("menu frames missing")
		initrd = os.path.join(self.bm, INITRD_NAME)
		if os.path.isfile(initrd):
			with open(initrd, "rb") as f:
				if hashlib.md5(f.read()).hexdigest() != conf.get("INITRD_MD5"):
					problems.append("initrd checksum mismatch")
		return problems

	# --- installation -------------------------------------------------------
	def payload(self, name):
		with open(os.path.join(self.payload_dir, name), "rb") as f:
			return f.read()

	def source_md5(self):
		"""md5 of the original 2nd-stage initrd the menu initrd is built from."""
		return hashlib.md5(self.read_bytes("STARTUP.cpio.gz")).hexdigest()

	def install_payload(self):
		"""Copy menu-init and runner.py and build the initrd. Returns its md5."""
		os.makedirs(self.bm, exist_ok=True)
		for name, mode in (("menu-init", 0o755), ("runner.py", 0o644)):
			data = self.payload(name)
			target = os.path.join(self.bm, name)
			atomic_write(target, data, mode)
			with open(target, "rb") as f:
				if f.read() != data:
					raise BootMenuError("%s: verification failed" % name)
		gz = build_initrd(self.read_bytes("STARTUP.cpio.gz"), self.payload("init"))
		target = os.path.join(self.bm, INITRD_NAME)
		atomic_write(target, gz)
		md5 = hashlib.md5(gz).hexdigest()
		with open(target, "rb") as f:
			if hashlib.md5(f.read()).hexdigest() != md5:
				raise BootMenuError("initrd: verification failed")
		return md5

	def mark_unverified(self):
		"""Set whenever STARTUP is pointed to the menu; the initrd wrapper removes
		it as soon as it runs. If STARTUP is found changed while the marker is
		still there, the menu never started: it must not be re-activated."""
		atomic_write(os.path.join(self.bm, UNVERIFIED), "%d\n" % int(time.time()))

	def reset_failures(self):
		for name in (".fails", ".running", ".wrapper_pending", "status"):
			try:
				os.remove(os.path.join(self.bm, name))
			except OSError:
				pass

	def prepare(self, settings, state, strict=True):
		"""Everything both enable() and try_once() need: the checks, the files
		in /boot/bootmenu and the configuration. Nothing here makes the box
		boot the menu - that is one line in the caller, and it comes last."""
		if not self.is_kexec_layout():
			raise BootMenuError("Vu+ kexec multiboot layout not found in %s" % self.boot)
		problems = self.recovery_problems(strict)
		if problems:
			raise BootMenuError("; ".join(problems))
		self.menu_line()
		md5 = self.install_payload()
		conf = self.read_conf()
		conf.update({k: str(v) for k, v in settings.items()})
		conf.update({"ENABLED": state, "VERSION": VERSION, "INITRD_MD5": md5, "SOURCE_MD5": self.source_md5(), "NOTIFIED": ""})
		problems = self.installation_problems(conf)
		if problems:
			raise BootMenuError("; ".join(problems))
		self.reset_failures()
		return conf

	def enable(self, settings, strict=True):
		"""Frames must already be in place. Order matters: nothing points to
		the menu until every file it needs has been written and verified."""
		conf = self.prepare(settings, ENABLED_ON, strict)
		conf["TRIAL"] = ""
		self.write_conf(conf)
		if not self.startup_is_menu():
			shutil.copyfile(self.path("STARTUP"), os.path.join(self.bm, "STARTUP.before"))
			self.mark_unverified()
		self.set_startup_menu()
		return conf

	def try_once(self, settings, strict=True):
		"""Load the menu at the next boot only, leaving STARTUP alone.

		STARTUP_ONCE is the Vu+ kexec way of booting something exactly once:
		the 1st stage uses it instead of STARTUP and the 2nd stage of whatever
		starts next deletes it. So the worst case of a trial is one boot that
		does not reach the menu, with the box still configured exactly as it
		was. It is the safe way to find out whether a receiver nobody has
		tested can load the menu at all.

		Refused when STARTUP already starts the menu. A trial ends by setting
		ENABLED back to 0, which in that state would leave STARTUP pointing at
		an initrd the wrapper then refuses to use - and the original 2nd stage
		would boot what the menu line names, the Recovery. There is nothing to
		try anyway: a menu that starts at every boot has already answered the
		question."""
		if self.startup_is_menu():
			raise BootMenuError("the boot menu already starts at every boot: there is nothing to try")
		conf = self.prepare(settings, ENABLED_ONCE, strict)
		conf["TRIAL"] = "pending"
		self.write_conf(conf)
		self.mark_unverified()
		atomic_write(self.path("STARTUP_ONCE"), self.menu_line())
		return conf

	def trial_outcome(self):
		"""What the trial of the previous boot proved, read from the two marks
		the boot itself leaves behind:

		ran      the menu ran and a slot was chosen - the receiver works
		menu     the initrd was loaded but the menu stage gave up (see the log)
		initrd   the initrd was never loaded: STARTUP_ONCE was ignored
		"""
		if os.path.exists(os.path.join(self.bm, UNVERIFIED)):
			return "initrd"
		return "ran" if self.status().startswith("OK") else "menu"

	def cancel_trial(self):
		"""Called at the next start, whatever happened: a trial lasts one boot.
		Also removes a STARTUP_ONCE that was never consumed, so that a trial
		which did not boot at all cannot be retried by accident."""
		outcome = self.trial_outcome()
		try:
			if ("initrd=" + INITRD_REL) in self.read_text("STARTUP_ONCE").split():
				os.remove(self.path("STARTUP_ONCE"))
		except OSError:
			pass
		# the outcome of the trial is the message the user gets; the ordinary
		# "the menu could not start" notice would only say the same twice
		self.update_conf(ENABLED=ENABLED_OFF, TRIAL=outcome, NOTIFIED=self.status())
		return outcome

	def disable(self, slot, settings=None):
		"""STARTUP first, then the flag: a power cut in between is harmless."""
		if self.startup_is_menu():
			self.set_startup_slot(slot)
		try:
			if ("initrd=" + INITRD_REL) in self.read_text("STARTUP_ONCE").split():
				os.remove(self.path("STARTUP_ONCE"))
		except OSError:
			pass
		conf = self.read_conf()
		conf.update({k: str(v) for k, v in (settings or {}).items()})
		conf["ENABLED"] = ENABLED_OFF
		self.write_conf(conf)
		return conf

	def on_session_start(self, current_slot):
		"""Called by the plugin in every OBH slot at startup.
		Returns a short description of what was done (or None)."""
		conf = self.read_conf()
		if conf.get("ENABLED") == ENABLED_ONCE:
			return "trial finished: %s" % self.cancel_trial()
		if conf.get("ENABLED") != ENABLED_ON:
			return None
		changes = {}
		if current_slot and int(current_slot) >= 1 and conf.get("LAST") != str(current_slot):
			changes["LAST"] = str(current_slot)
		action = None
		if not self.startup_is_menu():
			problems = self.installation_problems(conf)
			if os.path.exists(os.path.join(self.bm, UNVERIFIED)):
				changes["ENABLED"] = "0"
				atomic_write(os.path.join(self.bm, "status"), "NEVER_RAN STARTUP changed before the menu ever started\n")
				action = "disabled: the menu never started since it was activated"
			elif problems:
				action = "not restored: " + "; ".join(problems)
			else:
				self.mark_unverified()
				self.set_startup_menu()
				action = "restored"
		if changes:
			conf.update(changes)
			self.write_conf(conf)
		return action

	def frames_signature(self):
		try:
			with open(os.path.join(self.frames, "menu.txt"), encoding="utf-8", errors="replace") as f:
				for line in f:
					if line.startswith("SIGNATURE="):
						return line[10:].strip()
		except OSError:
			pass
		return ""
