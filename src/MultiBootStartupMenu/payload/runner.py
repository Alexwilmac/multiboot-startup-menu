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
KEY_YELLOW, KEY_BLUE = 400, 401
KEYS_PATTERN = (KEY_YELLOW, KEY_BLUE)
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

# The size the frames were drawn for. WIDTH/HEIGHT are what the framebuffer is
# actually used at, which is the same thing unless FBMODE=keep is in force - see
# FrameBuffer.setup().
FRAME_W, FRAME_H = 1920, 1080
WIDTH, HEIGHT = FRAME_W, FRAME_H
OFFX, OFFY = 0, 0
LCD_W, LCD_H = 0, 0    # the front display, from menu.txt's LCDSIZE= line

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
			if line.startswith("SIZE="):
				global FRAME_W, FRAME_H
				FRAME_W, FRAME_H = (int(v) for v in line[5:].split("x", 1))
			elif line.startswith("LCDSIZE="):
				global LCD_W, LCD_H
				LCD_W, LCD_H = (int(v) for v in line[8:].split("x", 1))
			elif line.startswith("COUNTMAX="):
				countmax = int(line[9:])
			elif line.startswith("ENTRY="):
				slot, startup, label = line[6:].split("|", 2)
				entries.append((int(slot), startup, label))
			elif line.startswith("RECOVERY="):
				startup, label = line[9:].split("|", 1)
				recovery = (0, startup, label)
	return entries, countmax, recovery


def load_frame(name, bounds=None):
	with open(FRAMES + "/" + name, "rb") as f:
		data = f.read()
	if data[:4] != b"BMF1":
		raise ValueError("bad frame file " + name)
	x, y, w, h = (int.from_bytes(data[i:i + 2], "little") for i in (4, 6, 8, 10))
	pix = zlib.decompress(data[12:])
	bw, bh = bounds or (FRAME_W, FRAME_H)
	if len(pix) != w * h * 4 or x + w > bw or y + h > bh:
		raise ValueError("bad frame geometry " + name)
	return x, y, w, h, pix


def screen_size():
	"""The resolution the receiver is driving, from the mode it is set to.
	None when it cannot be read: the OSD rectangle is then left alone, which
	is always safe."""
	try:
		with open(ROOT + "/proc/stb/video/videomode") as f:
			text = f.read().strip().lower()
	except OSError:
		return None
	digits = ""
	for ch in text:
		if ch.isdigit():
			digits += ch
		else:
			break
	return {"2160": (3840, 2160), "1080": (1920, 1080), "720": (1280, 720),
		"576": (720, 576), "480": (720, 480)}.get(digits)


def osd_rectangle(mode, fb, screen):
	"""Where the framebuffer should land on the screen, in the 720x576 units
	the driver takes (720x576 means the whole screen, whatever it is).

	native: the framebuffer at its own size, pixel for pixel, in the middle of
	the screen. No scaling at all, so nothing can soften it - at the price of
	a smaller picture.
	double: twice the size, anchored at the top left. On a 1440-row
	framebuffer that reaches past the bottom of a 2160-row screen, which is
	the point: the menu is drawn in the top 1080 rows, and those land on the
	whole screen at exactly twice the size - the same clean doubling the
	enigma2 GUI gets."""
	fw, fh = fb
	sw, sh = screen
	if mode == "native":
		w = int(round(720.0 * fw / sw))
		h = int(round(576.0 * fh / sh))
	elif mode == "double":
		w = int(round(720.0 * fw * 2 / sw))
		h = int(round(576.0 * fh * 2 / sh))
	else:
		return None
	if not (0 < w <= 720 * 4 and 0 < h <= 576 * 4):
		return None
	left = max(0, (720 - w) // 2) if mode == "native" else 0
	top = max(0, (576 - h) // 2) if mode == "native" else 0
	return left, w, top, h


def write_osd(left, width, top, height):
	for name, value in (("dst_left", left), ("dst_width", width), ("dst_top", top),
			("dst_height", height), ("dst_width", width)):
		with open("/proc/stb/fb/" + name, "w") as f:
			f.write("%08X\n" % value)
	try:
		with open("/proc/stb/fb/dst_apply", "w") as f:
			f.write("1")
	except OSError:
		pass            # not on every receiver: there the values apply as they are written


class FrontPanel:
	"""The small colour screen on the front of the receiver.

	It is worth the trouble because it is the only part of the menu that can
	be read when the television is off, on another input, or still settling
	the HDMI link - which is exactly when being unable to choose a slot is
	most annoying.

	Two things make it different from the television framebuffer. It takes a
	whole frame at a time, so the tiles are composed into a buffer here and
	the buffer goes over in one write; and its backlight is off until enigma2
	turns it on, so the picture would be sitting there in the dark unless the
	brightness is turned up first."""

	DEVICES = ("/dev/dbox/oled0", "/dev/dbox/lcd0", "/dev/oled0", "/dev/lcd0")
	BRIGHTNESS = ("/proc/stb/fp/oled_brightness", "/proc/stb/lcd/oled_brightness",
		"/proc/stb/fp/lcd_brightness", "/proc/stb/lcd/brightness")

	def __init__(self, size, brightness="255"):
		self.w, self.h = int(size[0]), int(size[1])
		self.stride = self.w * 4
		self.buf = bytearray(self.stride * self.h)
		self.dirty = True
		self.path = None
		for name in self.DEVICES:
			if os.path.exists(ROOT + name):
				self.path = ROOT + name
				break
		if self.path is None:
			raise OSError("no front display among %s" % ", ".join(self.DEVICES))
		self.fd = os.open(self.path, os.O_WRONLY)
		self.light(brightness)
		# some of these panels can show live television instead of what is
		# written to them; nothing is playing here, so it would only hide us
		self.set_node("/proc/stb/lcd/live_enable", "disable")

	# ------------------------------------------------------------------
	def set_node(self, path, value):
		try:
			with open(ROOT + path, "w") as f:
				f.write(value)
			return True
		except OSError:
			return False

	def light(self, value):
		for path in self.BRIGHTNESS:
			if os.path.exists(ROOT + path) and self.set_node(path, str(value)):
				log("front display: %s set to %s" % (path, value))
				return path
		log("front display: no brightness control found, it may stay dark")
		return None

	def put(self, frame):
		x, y, w, h, pix = frame
		if x + w > self.w or y + h > self.h:
			raise ValueError("front display frame does not fit")
		row = w * 4
		for r in range(h):
			start = (y + r) * self.stride + x * 4
			self.buf[start:start + row] = pix[r * row:(r + 1) * row]
		self.dirty = True

	def flush(self):
		if not self.dirty:
			return
		try:
			os.lseek(self.fd, 0, os.SEEK_SET)
		except OSError:
			pass        # a character device that does not seek: it takes whole frames anyway
		written = 0
		while written < len(self.buf):
			n = os.write(self.fd, self.buf[written:])
			if not n:
				break
			written += n
		self.dirty = False

	def close(self):
		try:
			os.close(self.fd)
		except OSError:
			pass


def frame_offsets(native, frame, osd=""):
	"""Where the frames go inside a framebuffer that is bigger than they are.

	Centred, except with OSDMODE=double: there the framebuffer is put on the
	screen at twice its size and its lower part falls off the bottom, so the
	menu has to sit at the top to be seen at all."""
	offx = max(0, (native[0] - frame[0]) // 2)
	if osd == "double":
		return offx, 0
	return offx, max(0, (native[1] - frame[1]) // 2)


def apply_osd():
	"""Tell the scaler about the framebuffer we have just set.

	menu-init writes the OSD rectangle before the menu starts, while the
	framebuffer is still the one the Recovery's driver set up - 1920x1440 on a
	Vu+ 4K. The scaler is latched against that source size. A moment later the
	mode is changed to 1920x1080 and nothing tells the scaler, so it goes on
	stretching 1080 lines as if they were 1440, on top of the upscale to the
	television's own resolution: sharp in the plugin's preview, soft on the
	screen. Writing the same values again here, once the framebuffer is what
	it will stay, is what makes the two agree."""
	if TEST:
		return
	conf = read_conf()
	mode = conf.get("OSDMODE", "").strip().lower()
	rect = None
	if mode in ("native", "double"):
		screen = screen_size()
		if screen:
			rect = osd_rectangle(mode, (WIDTH, HEIGHT), screen)
			if rect is None:
				log("osd %s: no usable rectangle for fb %dx%d on screen %dx%d"
					% (mode, WIDTH, HEIGHT, screen[0], screen[1]))
		else:
			log("osd %s: the output resolution could not be read, left alone" % mode)
	if rect is None:
		parts = conf.get("OSD", "").split(",")
		if len(parts) != 4 or not all(p.strip().isdigit() for p in parts):
			return
		rect = tuple(int(p) for p in parts)
		mode = "manual"
	left, width, top, height = rect
	try:
		write_osd(left, width, top, height)
		log("osd %s: %d,%d,%d,%d (left,width,top,height in 720x576 units)"
			% (mode, left, width, top, height))
	except OSError as err:
		log("osd could not be applied: %s" % err)


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
		global WIDTH, HEIGHT, OFFX, OFFY
		var = bytearray(160)
		fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, var, True)
		native = (u32(var, 0), u32(var, 4))
		log("fb before: %dx%d virtual %dx%d bpp %d" % (native[0], native[1], u32(var, 8), u32(var, 12), u32(var, 24)))
		# what the driver of this Recovery brings up by itself, for the plugin
		try:
			update_conf("FBNATIVE", "%dx%d" % native)
		except OSError as err:
			log("cannot record the native framebuffer size: %s" % err)

		# FBMODE=keep: do not touch the mode at all, and draw the frames into
		# the framebuffer as the driver set it up, unscaled and centred.
		#
		# It exists because asking for 1920x1080 is accepted and read back as
		# 1920x1080 while the picture on screen is still stretched, which says
		# the mode change does not reach whatever actually feeds the screen.
		# With FBMODE=keep nothing is asked of the driver, so what appears on
		# screen tells us what the driver was going to do anyway - and that is
		# the one thing that cannot be worked out from here.
		# The frames are drawn for the framebuffer this receiver actually has,
		# so normally there is nothing to ask the driver for: what it set up is
		# what we want. "force" goes back to asking for the frames' size, which
		# is what every version up to 0.7.2 did, and is the way out if leaving
		# the mode alone turns out to be wrong somewhere.
		conf = read_conf()
		mode = conf.get("FBMODE", "")
		osd = conf.get("OSDMODE", "").strip().lower()
		sane = 640 <= native[0] <= 4096 and 480 <= native[1] <= 2304
		# An OSD mode places the framebuffer on the screen itself, so the
		# framebuffer must be left exactly as the driver made it.
		if sane and (osd in ("native", "double") or mode == "keep"
				or (mode != "force" and native == (FRAME_W, FRAME_H))):
			WIDTH, HEIGHT = native
			OFFX, OFFY = frame_offsets(native, (FRAME_W, FRAME_H), osd)
			why = (" (OSDMODE=%s)" % osd) if osd else (" (FBMODE=keep)" if mode == "keep" else "")
			log("framebuffer left as it is: %dx%d, frames %dx%d drawn at +%d+%d%s"
				% (WIDTH, HEIGHT, FRAME_W, FRAME_H, OFFX, OFFY, why))
			size = self.finish_setup(var, clear=True)
			apply_osd()
			return size

		# same settings as enigma2 fbClass::SetMode(1920, 1080, 32)
		WIDTH, HEIGHT = FRAME_W, FRAME_H
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
		apply_osd()
		return self.finish_setup(var)

	def finish_setup(self, var, clear=False):
		import fcntl
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
		self.stride = WIDTH * 4
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
		self.clear_first = clear
		return size

	def put(self, frame):
		x, y, w, h, pix = frame
		if getattr(self, "clear_first", False):
			# the frames do not cover the whole framebuffer: everything around
			# them is whatever the driver left there
			self.mem[:self.stride * HEIGHT] = b"\0" * (self.stride * HEIGHT)
			self.clear_first = False
		x, y = x + OFFX, y + OFFY
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
		self.lcd = self.open_lcd()
		self.inputs = Inputs()
		self.alive = 0
		self.alive_at = 0.0
		write_file(RUN + "/runner.pid", "%d\n" % os.getpid())

	def open_lcd(self):
		"""The front display, when this receiver has one the plugin could draw
		for. Everything about it is optional: a receiver without one, or with
		one the plugin does not know how to use, simply gets the menu on the
		television, and nothing here is allowed to stop the menu."""
		if not (LCD_W and LCD_H):
			return None
		if self.conf.get("LCD", "1") == "0":
			log("front display: switched off in the configuration")
			return None
		try:
			panel = FrontPanel((LCD_W, LCD_H), self.conf.get("LCDBRIGHT") or "255")
			log("front display: %dx%d on %s" % (LCD_W, LCD_H, panel.path))
			return panel
		except (OSError, ValueError) as err:
			log("front display not used: %s" % err)
			return None

	def lcd_put(self, name, flush=True):
		"""Draw on the front panel, if there is one. A frame that is missing
		or broken costs the panel, never the menu."""
		if self.lcd is None:
			return
		try:
			self.lcd.put(load_frame(name, (LCD_W, LCD_H)))
			if flush:
				self.lcd.flush()
		except (OSError, ValueError, zlib.error) as err:
			log("front display: %s not shown (%s), giving up on it" % (name, err))
			self.lcd.close()
			self.lcd = None

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
		self.lcd_put("lcd_item_%d.bmf" % index)
		self.sel = index

	def show_footer(self, name):
		self.fb.put(load_frame(name))
		self.footer = name

	def show_pattern(self):
		"""A test pattern written 1:1 into the framebuffer.

		Nothing can be read back from the screen, so this is the only way to
		find out what the receiver does to the picture between the framebuffer
		and the panel. The framebuffer here is 1440 rows and the output is
		2160, so every 2 rows become 3: whether that is done by repeating rows
		or by mixing them decides whether the menu can be drawn sharply at all,
		and the two look completely different on these bands.

		Four bands, top to bottom, marked at the left by a black bar 1 to 4
		units wide so a photograph can be read without any text:
		  1  vertical lines, 1 pixel on, 1 pixel off  (the horizontal axis)
		  2  horizontal lines, 1 row on, 1 row off
		  3  horizontal lines, 2 rows on, 2 rows off
		  4  horizontal lines, 3 rows on, 3 rows off
		The left eighth stays solid white, as a reference for plain white.

		Not part of the menu: it is reached with YELLOW or BLUE on the boot
		screen and nothing announces it."""
		mem, stride = self.fb.mem, self.fb.stride
		white, black = b"\xff\xff\xff\xff", b"\x00\x00\x00\xff"
		ref = WIDTH // 8
		w_row = white * WIDTH
		b_row = white * ref + black * (WIDTH - ref)
		v_row = bytearray(w_row)
		for x in range(ref, WIDTH, 2):
			v_row[x * 4:x * 4 + 4] = black
		v_row = bytes(v_row)

		band = HEIGHT // 4
		unit = max(8, ref // 4)
		for i, n in enumerate((0, 1, 2, 3)):
			y0 = i * band
			y1 = HEIGHT if i == 3 else y0 + band
			for y in range(y0, y1):
				row = v_row if n == 0 else (w_row if ((y - y0) // n) % 2 == 0 else b_row)
				mem[y * stride:y * stride + WIDTH * 4] = row
			bar = black * (unit * (i + 1))
			for y in range(y0 + 8, min(y1, y0 + 48)):
				mem[y * stride:y * stride + len(bar)] = bar
		self.fb.blit()
		self.footer = "pattern"  # so the idle footer is not drawn over it
		log("test pattern: fb %dx%d, bands of %d rows, marker unit %d px; "
			"1 = vertical 1 px, 2 = horizontal 1 row, 3 = horizontal 2 rows, "
			"4 = horizontal 3 rows, left eighth solid white"
			% (WIDTH, HEIGHT, band, unit))

	def show_count(self, seconds):
		"""The countdown badge sits on the title line, not in the footer: it is
		its own small area, so the footer keeps showing the key hints."""
		self.fb.put(load_frame("count_%d.bmf" % seconds))
		self.lcd_put("lcd_count_%d.bmf" % seconds)

	def clear_count(self):
		self.lcd_put("lcd_count_off.bmf")
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
		self.lcd_put("lcd_boot_%d.bmf" % i if i != self.RECOVERY else "lcd_boot_recovery.bmf")
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
				if code in KEYS_PATTERN and value == 1:
					self.show_pattern()
				elif code in KEYS_PREV:
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
