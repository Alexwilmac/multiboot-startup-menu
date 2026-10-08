# -*- coding: utf-8 -*-
# MultiBootStartupMenu - menu runner
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# Started by /bootmenu/menu-init with the Recovery's python3 (stdlib only).
# Shows the frames pre-rendered by the plugin on /dev/fb0, reads the remote
# control from /dev/input/event*, writes the choice to /run/bootmenu/choice
# ("<slot> <STARTUP file>") and exits with 0. Any other exit code makes
# menu-init boot the default slot through its fail-safe.
#
# MBSM_TESTROOT / MBSM_ROOTDEV are only used by the off-box test suite.

import os
import sys
import time
import zlib
import select

ROOT = os.environ.get("MBSM_TESTROOT", "")
TEST = bool(ROOT)
BM = ROOT + "/bootmenu"
CONF = BM + "/bootmenu.conf"
FRAMES = BM + "/frames"
RUN = ROOT + "/run/bootmenu"
IDLE_LIMIT = 300  # seconds without keys after the countdown was stopped

# linux/input-event-codes.h
EV_KEY = 1
KEY_ESC, KEY_ENTER = 1, 28
KEY_UP, KEY_PAGEUP, KEY_LEFT, KEY_RIGHT, KEY_DOWN, KEY_PAGEDOWN = 103, 104, 105, 106, 108, 109
KEY_EXIT, KEY_OK = 174, 352
KEY_RED, KEY_GREEN = 398, 399
KEY_CHANNELUP, KEY_CHANNELDOWN = 402, 403
DIGITS = {11: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9}
KEYS_PREV = (KEY_UP, KEY_LEFT, KEY_PAGEUP, KEY_CHANNELUP)
KEYS_NEXT = (KEY_DOWN, KEY_RIGHT, KEY_PAGEDOWN, KEY_CHANNELDOWN)
KEYS_OK = (KEY_OK, KEY_ENTER, KEY_GREEN)

# linux/fb.h
FBIOGET_VSCREENINFO = 0x4600
FBIOPUT_VSCREENINFO = 0x4601
FBIOGET_FSCREENINFO = 0x4602
FBIOPAN_DISPLAY = 0x4606
FB_ACTIVATE_ALL = 64
FBIO_SET_MANUAL_BLIT = 0x40014621  # _IOW('F', 0x21, __u8)
FBIO_BLIT = 0x22
KDSETMODE, KD_GRAPHICS = 0x4B3A, 1

WIDTH, HEIGHT = 1920, 1080

_64BIT = os.uname().machine in ("aarch64", "arm64", "x86_64", "mips64")
LONG = 8 if _64BIT else 4
EVSZ = 24 if _64BIT else 16  # struct input_event


def log(msg):
	sys.stdout.write("%9.2f %s\n" % (time.monotonic(), msg))
	sys.stdout.flush()


def u32(buf, off):
	return int.from_bytes(buf[off:off + 4], "little")


def put_u32(buf, off, value):
	buf[off:off + 4] = int(value).to_bytes(4, "little")


def read_conf():
	conf = {}
	try:
		with open(CONF, encoding="utf-8", errors="replace") as f:
			for line in f:
				line = line.strip()
				if line and not line.startswith("#") and "=" in line:
					key, value = line.split("=", 1)
					conf[key.strip()] = value.strip()
	except OSError as err:
		log("cannot read %s: %s" % (CONF, err))
	return conf


def update_conf(key, value):
	with open(CONF, encoding="utf-8", errors="replace") as f:
		lines = f.read().splitlines()
	if not any(line.startswith("ENABLED=") for line in lines):
		raise OSError("unexpected content in %s" % CONF)
	out = []
	found = False
	for line in lines:
		if line.startswith(key + "="):
			out.append("%s=%s" % (key, value))
			found = True
		else:
			out.append(line)
	if not found:
		out.append("%s=%s" % (key, value))
	tmp = CONF + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		f.write("\n".join(out) + "\n")
		f.flush()
		os.fsync(f.fileno())
	os.rename(tmp, CONF)


def write_file(path, text):
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)
		f.flush()
		os.fsync(f.fileno())


def load_menu():
	entries = []
	countmax = 0
	recovery = None
	with open(FRAMES + "/menu.txt", encoding="utf-8", errors="replace") as f:
		for line in f:
			line = line.rstrip("\n")
			if line.startswith("COUNTMAX="):
				countmax = int(line[9:])
			elif line.startswith("ENTRY="):
				slot, startup, label = line[6:].split("|", 2)
				entries.append((int(slot), startup, label))
			elif line.startswith("RECOVERY="):
				startup, label = line[9:].split("|", 1)
				recovery = (0, startup, label)
	return entries, countmax, recovery


def load_frame(name):
	with open(FRAMES + "/" + name, "rb") as f:
		data = f.read()
	if data[:4] != b"BMF1":
		raise ValueError("bad frame file " + name)
	x, y, w, h = (int.from_bytes(data[i:i + 2], "little") for i in (4, 6, 8, 10))
	pix = zlib.decompress(data[12:])
	if len(pix) != w * h * 4 or x + w > WIDTH or y + h > HEIGHT:
		raise ValueError("bad frame geometry " + name)
	return x, y, w, h, pix


class FrameBuffer:
	def __init__(self, device):
		import mmap
		self.fd = os.open(device, os.O_RDWR)
		self.manual = False
		self.stride = WIDTH * 4
		size = self.stride * HEIGHT
		if not TEST:
			size = self.setup()
		self.mem = mmap.mmap(self.fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)

	def setup(self):
		import fcntl
		try:
			tty = os.open("/dev/tty0", os.O_RDWR)
			fcntl.ioctl(tty, KDSETMODE, KD_GRAPHICS)
			os.close(tty)
		except OSError:
			pass
		var = bytearray(160)
		fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, var, True)
		log("fb before: %dx%d virtual %dx%d bpp %d" % (u32(var, 0), u32(var, 4), u32(var, 8), u32(var, 12), u32(var, 24)))
		# same settings as enigma2 fbClass::SetMode(1920, 1080, 32)
		put_u32(var, 0, WIDTH)
		put_u32(var, 4, HEIGHT)
		put_u32(var, 8, WIDTH)
		put_u32(var, 12, HEIGHT * 2)
		put_u32(var, 16, 0)
		put_u32(var, 20, 0)
		put_u32(var, 24, 32)
		for off, (bitoff, bitlen) in ((32, (16, 8)), (44, (8, 8)), (56, (0, 8)), (68, (24, 8))):
			put_u32(var, off, bitoff)
			put_u32(var, off + 4, bitlen)
			put_u32(var, off + 8, 0)
		put_u32(var, 84, FB_ACTIVATE_ALL)
		put_u32(var, 88, 0)
		put_u32(var, 92, 0)
		try:
			fcntl.ioctl(self.fd, FBIOPUT_VSCREENINFO, var, True)
		except OSError:
			put_u32(var, 12, HEIGHT)
			try:
				fcntl.ioctl(self.fd, FBIOPUT_VSCREENINFO, var, True)
			except OSError as err:
				log("FBIOPUT_VSCREENINFO failed: %s" % err)
		fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, var, True)
		xres, yres, bpp = u32(var, 0), u32(var, 4), u32(var, 24)
		log("fb after: %dx%d virtual %dx%d bpp %d" % (xres, yres, u32(var, 8), u32(var, 12), bpp))
		if (xres, yres, bpp) != (WIDTH, HEIGHT, 32):
			raise RuntimeError("framebuffer mode %dx%dx%d not usable" % (xres, yres, bpp))
		if u32(var, 20):
			put_u32(var, 16, 0)
			put_u32(var, 20, 0)
			try:
				fcntl.ioctl(self.fd, FBIOPAN_DISPLAY, var, True)
			except OSError as err:
				log("FBIOPAN_DISPLAY failed: %s" % err)
		fix = bytearray(96)
		fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, fix, True)
		smem_len = u32(fix, 16 + LONG)
		line_length = u32(fix, 44 if LONG == 4 else 48)
		if line_length >= WIDTH * 4:
			self.stride = line_length
		log("fb smem_len %d line_length %d" % (smem_len, line_length))
		size = self.stride * HEIGHT
		if smem_len < size:
			raise RuntimeError("framebuffer memory too small: %d" % smem_len)
		try:
			fcntl.ioctl(self.fd, FBIO_SET_MANUAL_BLIT, bytes([1]))
			self.manual = True
		except OSError as err:
			log("manual blit not available: %s" % err)
		return size

	def put(self, frame):
		x, y, w, h, pix = frame
		row = w * 4
		if x == 0 and w == WIDTH and self.stride == row:
			start = y * self.stride
			self.mem[start:start + len(pix)] = pix
		else:
			view = memoryview(pix)
			for r in range(h):
				start = (y + r) * self.stride + x * 4
				self.mem[start:start + row] = view[r * row:(r + 1) * row]

	def blit(self):
		if self.manual:
			import fcntl
			try:
				fcntl.ioctl(self.fd, FBIO_BLIT, 0)
			except OSError as err:
				log("FBIO_BLIT failed: %s" % err)
		elif TEST:
			self.mem.flush()


class Inputs:
	def __init__(self):
		self.fds = []
		folder = ROOT + "/dev/input"
		try:
			names = sorted(os.listdir(folder))
		except OSError:
			names = []
		for name in names:
			if not name.startswith("event"):
				continue
			try:
				fd = os.open(folder + "/" + name, os.O_RDONLY | os.O_NONBLOCK)
			except OSError as err:
				log("cannot open %s: %s" % (name, err))
				continue
			self.fds.append(fd)
			label = ""
			try:
				with open("/sys/class/input/%s/device/name" % name, encoding="utf-8", errors="replace") as f:
					label = f.read().strip()
			except OSError:
				pass
			log("input %s %s" % (name, label))
		if not self.fds:
			log("no input device: the default image will start after the countdown")

	def flush(self):
		for fd in self.fds:
			try:
				while os.read(fd, EVSZ * 64):
					pass
			except OSError:
				pass

	def keys(self, timeout):
		if not self.fds:
			time.sleep(timeout)
			return []
		try:
			ready = select.select(self.fds, [], [], timeout)[0]
		except OSError:
			time.sleep(timeout)
			return []
		result = []
		for fd in ready:
			try:
				data = os.read(fd, EVSZ * 64)
			except OSError:
				continue
			for i in range(0, len(data) - EVSZ + 1, EVSZ):
				ev = data[i:i + EVSZ]
				etype = int.from_bytes(ev[EVSZ - 8:EVSZ - 6], "little")
				code = int.from_bytes(ev[EVSZ - 6:EVSZ - 4], "little")
				value = int.from_bytes(ev[EVSZ - 4:EVSZ], "little", signed=True)
				if etype == EV_KEY and value in (1, 2):
					result.append((code, value))
		return result


def this_root():
	if not TEST:
		try:
			with open("/proc/cmdline", encoding="utf-8", errors="replace") as f:
				for token in f.read().split():
					if token.startswith("root="):
						return token[5:]
		except OSError:
			pass
	return os.environ.get("MBSM_ROOTDEV", "/dev/mmcblk0p4")


def bootable(slot, startup, rootdev):
	path = ROOT + "/" + startup
	if not os.path.isfile(path):
		return "%s is missing" % startup
	with open(path, encoding="utf-8", errors="replace") as f:
		tokens = dict(t.split("=", 1) for t in f.read().replace('"', "").split() if "=" in t)
	if tokens.get("root") != rootdev:
		return ""  # slot on another device (USB): checked by the kexec stage itself
	kernel = tokens.get("kernel", "").lstrip("/")
	if not kernel or not os.path.isfile(ROOT + "/" + kernel):
		return "kernel %s is missing" % kernel
	sub = tokens.get("rootsubdir", "").strip("/")
	root_image = sub in ("", "linuxrootfs0")  # the Recovery: its rootfs is the partition root
	image = ROOT if root_image else ROOT + "/" + sub
	if not os.path.isfile(image + "/usr/bin/enigma2"):
		# the Recovery may be a minimal image without enigma2: /sbin/init is enough
		if not (root_image and os.path.isfile(image + "/sbin/init")):
			return "no image in %s" % (sub or "/")
	return ""


class Menu:
	def __init__(self):
		self.conf = read_conf()
		self.entries, self.countmax, self.recovery = load_menu()
		if not self.entries:
			raise RuntimeError("menu.txt has no entries")
		try:
			self.timeout = int(self.conf.get("TIMEOUT", "10"))
		except ValueError:
			self.timeout = 10
		self.timeout = max(1, min(self.timeout, self.countmax or 1))
		self.rootdev = this_root()
		self.sel = self.default_index()
		self.footer = None
		self.fb = FrameBuffer(ROOT + "/dev/fb0")
		self.inputs = Inputs()
		self.alive = 0
		self.alive_at = 0.0
		write_file(RUN + "/runner.pid", "%d\n" % os.getpid())

	def default_index(self):
		wanted = self.conf.get("DEFAULT", "last")
		if wanted == "last":
			wanted = self.conf.get("LAST", "")
		for i, entry in enumerate(self.entries):
			if str(entry[0]) == wanted:
				return i
		return 0

	def heartbeat(self):
		now = time.monotonic()
		if now - self.alive_at >= 1.0:
			self.alive += 1
			self.alive_at = now
			try:
				write_file(RUN + "/alive", "%d\n" % self.alive)
			except OSError:
				pass

	def show_item(self, index):
		self.fb.put(load_frame("item_%d.bmf" % index))
		self.sel = index

	def show_footer(self, name):
		self.fb.put(load_frame(name))
		self.footer = name

	def show_count(self, seconds):
		"""The countdown badge sits on the title line, not in the footer: it is
		its own small area, so the footer keeps showing the key hints."""
		self.fb.put(load_frame("count_%d.bmf" % seconds))

	def clear_count(self):
		try:
			self.fb.put(load_frame("count_off.bmf"))
		except (OSError, ValueError) as err:  # frames from an older version
			log("count_off.bmf: %s" % err)
			self.show_item(self.sel)
			self.footer = None

	def mark_drawn(self):
		for name in (".running",):
			try:
				os.remove(BM + "/" + name)
			except OSError:
				pass
		try:
			write_file(BM + "/.fails", "0\n")
		except OSError as err:
			log("cannot reset .fails: %s" % err)

	RECOVERY = -1  # the Recovery when it is not one of the listed entries

	def entry(self, index):
		return self.recovery if index == self.RECOVERY else self.entries[index]

	def auto_order(self, index):
		"""When the countdown expires and the chosen image cannot be started,
		the Recovery comes first: it looks unmistakably different, so a boot
		that went wrong cannot be taken for the image that was asked for.
		The other slots are only the last resort."""
		shown = [i for i, e in enumerate(self.entries) if e[0] == 0 and i != index]
		order = [index] + shown
		if not shown and self.recovery and index != self.RECOVERY:
			order.append(self.RECOVERY)
		return order + [i for i in range(len(self.entries)) if i != index and i not in shown]

	def start(self, index, automatic):
		order = self.auto_order(index) if automatic else [index]
		for i in order:
			slot, startup, label = self.entry(i)
			problem = bootable(slot, startup, self.rootdev)
			if not problem:
				break
			log("entry %s (%s) not bootable: %s" % (i, label, problem))
			if not automatic:
				self.show_footer("error.bmf")
				self.fb.blit()
				time.sleep(2.5)
				self.show_footer("idle.bmf")
				self.fb.blit()
				return False
		else:
			raise RuntimeError("no bootable entry")
		if i != self.sel and i != self.RECOVERY:
			self.show_item(i)
		self.clear_count()
		self.show_footer("boot_%d.bmf" % i if i != self.RECOVERY else "boot_recovery.bmf")
		self.fb.blit()
		log("chosen entry %s: slot %d %s (%s)" % (i, slot, startup, label))
		write_file(RUN + "/choice", "%d %s\n" % (slot, startup))
		if slot >= 1:
			try:
				update_conf("LAST", str(slot))
			except OSError as err:
				log("cannot update LAST: %s" % err)
		return True

	def run(self):
		self.inputs.flush()
		self.show_item(self.sel)
		self.show_footer("idle.bmf")
		self.show_count(self.timeout)
		self.fb.blit()
		self.mark_drawn()
		log("menu drawn: %d entries, default entry %d, timeout %d s" % (len(self.entries), self.sel, self.timeout))
		started = time.monotonic()
		countdown = True
		shown = self.timeout
		last_key = started
		while True:
			self.heartbeat()
			now = time.monotonic()
			if countdown:
				remaining = self.timeout - int(now - started)
				if remaining <= 0:
					log("countdown expired")
					if self.start(self.sel, True):
						return
				elif remaining != shown:
					self.show_count(remaining)
					self.fb.blit()
					shown = remaining
			elif now - last_key > IDLE_LIMIT:
				log("no key for %d s" % IDLE_LIMIT)
				if self.start(self.sel, True):
					return
			for code, value in self.inputs.keys(0.2):
				log("key %d value %d" % (code, value))
				last_key = time.monotonic()
				redraw = False
				if countdown:
					countdown = False
					self.clear_count()
					self.footer = None
				if code in KEYS_PREV:
					self.show_item((self.sel - 1) % len(self.entries))
					redraw = True
				elif code in KEYS_NEXT:
					self.show_item((self.sel + 1) % len(self.entries))
					redraw = True
				elif code in KEYS_OK and value == 1:
					if self.start(self.sel, False):
						return
				elif code in DIGITS and value == 1:
					slot = DIGITS[code]
					for i, entry in enumerate(self.entries):
						if entry[0] == slot:
							self.show_item(i)
							self.fb.blit()
							if self.start(i, False):
								return
							break
				if redraw or self.footer is None:
					self.show_footer("idle.bmf")
					self.fb.blit()


def main():
	try:
		sys.stdout.reconfigure(encoding="utf-8", errors="replace")
	except Exception:
		pass
	log("MultiBootStartupMenu runner, python %s, event size %d" % (sys.version.split()[0], EVSZ))
	try:
		os.makedirs(RUN, exist_ok=True)
		Menu().run()
	except Exception as err:
		import traceback
		traceback.print_exc(file=sys.stdout)
		log("runner failed: %s" % err)
		return 3
	return 0


if __name__ == "__main__":
	sys.exit(main())
