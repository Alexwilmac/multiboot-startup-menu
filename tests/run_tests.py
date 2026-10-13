# Off-box test suite for MultiBootStartupMenu
#   python3 tests/run_tests.py [quick]
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SRC = os.path.join(PROJECT, "src")
OUT = os.path.join(PROJECT, "out", "tests")
PAYLOAD = os.path.join(SRC, "MultiBootStartupMenu", "payload")
FONTS = os.path.join(PROJECT, "..", "obh", "data", "fonts")
BB = os.path.join(OUT, "bb")
QUICK = "quick" in sys.argv

sys.path[:0] = [os.path.join(HERE, "stubs"), SRC, HERE]
os.makedirs(os.path.join(OUT, "plugins", "SystemPlugins"), exist_ok=True)
link = os.path.join(OUT, "plugins", "SystemPlugins", "MultiBootStartupMenu")
if not os.path.islink(link):
	os.symlink(os.path.join(SRC, "MultiBootStartupMenu"), link)
os.environ["MBSM_PLUGINS"] = os.path.join(OUT, "plugins")

import enigma  # noqa: E402  (stub)
import fakeboot  # noqa: E402
from MultiBootStartupMenu import core, render  # noqa: E402

render.FONT_DIRS = (FONTS,)
RESULTS = []


def check(name, cond, detail=""):
	RESULTS.append((name, bool(cond), detail))
	print("%s  %s%s" % ("PASS" if cond else "FAIL", name, ("  -- " + str(detail)) if detail and not cond else ""))


def read(path, default=None):
	try:
		with open(path) as f:
			return f.read()
	except OSError:
		return default


def conf_of(root):
	return core.BootEnv(root).read_conf()


def notifications():
	from Tools.Notifications import NOTIFICATIONS
	return list(NOTIFICATIONS)


def frame_geometry(path):
	with open(path, "rb") as f:
		head = f.read(12)
	assert head[:4] == b"BMF1", path
	return tuple(int.from_bytes(head[i:i + 2], "little") for i in (4, 6, 8, 10))


def count_area(bm):
	"""x, y, w, h of the countdown frames: the same for all of them, on the
	title line (not in the footer) and clear of the left half of the screen."""
	frames = os.path.join(bm, "frames")
	boxes = {frame_geometry(os.path.join(frames, name)) for name in os.listdir(frames) if name.startswith("count_")}
	if len(boxes) != 1:
		return "different geometries: %s" % sorted(boxes)
	x, y, w, h = boxes.pop()
	if y >= render.FOOTER_Y or y + h > render.DIVIDER_Y or x < render.W // 3 or x + w > render.W:
		return "unexpected area %s" % ((x, y, w, h),)
	return True


# ---------------------------------------------------------------------------
# busybox applets only, like on the box
def make_busybox_dir():
	if os.path.isdir(BB):
		return
	os.makedirs(BB)
	applets = subprocess.check_output(["busybox", "--list"]).decode().split()
	for a in applets:
		os.symlink(shutil.which("busybox"), os.path.join(BB, a))


# ---------------------------------------------------------------------------
class FakeSession:
	"""Models StartEnigma.Session closely enough to reproduce the crash of
	0.1.0: open() refuses to work while the dialog stack is not empty and
	in_exec is False, which is exactly the state between Session.close()
	(execEnd) and the deferred pop of the closed dialog (delay_timer ->
	popCurrent -> execBegin)."""

	def __init__(self):
		self.log = []
		self.stack = []  # dialogs on screen, the last one is the current one
		self.dialog_stack = []
		self.current_dialog = None
		self.in_exec = False
		self.delay_timer = enigma.eTimer()
		self.delay_timer.callback.append(self.processDelay)

	def open(self, screen, *args, **kwargs):
		if self.dialog_stack and not self.in_exec:
			raise RuntimeError("[StartEnigma] Error: Modal open are allowed only from a screen which is modal!")
		if self.current_dialog is not None:  # pushCurrent
			self.dialog_stack.append(self.current_dialog)
			self.in_exec = False  # execEnd
		obj = screen(self, *args, **kwargs)
		obj._callback = None
		obj._retval = ()
		self.current_dialog = obj
		self.stack.append(obj)
		self.log.append((screen.__name__, args, kwargs))
		self.in_exec = True  # execBegin
		return obj

	def openWithCallback(self, callback, screen, *args, **kwargs):
		obj = self.open(screen, *args, **kwargs)
		obj._callback = callback
		return obj

	def close(self, screen, *retval):
		if not self.in_exec:
			return  # "[StartEnigma] Close after exec!"
		assert screen is self.current_dialog, "close() of a dialog that is not the current one"
		screen._retval = retval
		self.in_exec = False  # execEnd
		self.delay_timer.start(0, True)

	def processDelay(self):
		dialog = self.current_dialog
		if dialog is None:
			return
		dialog.doClose()
		if dialog in self.stack:
			self.stack.remove(dialog)
		self.current_dialog = self.dialog_stack.pop() if self.dialog_stack else None  # popCurrent
		self.in_exec = self.current_dialog is not None  # execBegin
		if dialog._callback:
			dialog._callback(*dialog._retval)


def plugin_env(root, current=3, images=None):
	core.BOOT = root
	from Components.SystemInfo import SystemInfo
	import Tools.Multiboot as tm
	SystemInfo["HasKexecMultiboot"] = True
	SystemInfo["MultiBootSlot"] = current
	SystemInfo["canMultiBoot"] = {
		0: {"startupfile": "STARTUP_RECOVERY", "slotType": ""},
		1: {"startupfile": "STARTUP_1", "slotType": "eMMC"},
		2: {"startupfile": "STARTUP_2", "slotType": "eMMC"},
		3: {"startupfile": "STARTUP_3", "slotType": "eMMC"},
	}
	tm.IMAGES = images or {
		1: {"imagename": "OpenBH 6.0.002 (13-09-2026)"},
		2: {"imagename": "OpenATV 7.6 (05-08-2026)"},
		3: {"imagename": "OpenBH 6.0.003 (27-09-2026)"},
	}


def enable_via_ui(root, timeout="3"):
	from MultiBootStartupMenu.ui import MultiBootStartupMenuSetup
	session = FakeSession()
	screen = session.open(MultiBootStartupMenuSetup)
	items_off = len(screen.list)
	screen.cfgEnabled.value = True
	screen.cfgTimeout.value = timeout
	screen.createSetup()
	items_on = len(screen.list)
	screen.keySave()
	enigma.run_timers()
	return session, screen, items_off, items_on


def test_plugin_enable(root):
	fakeboot.build(root)
	plugin_env(root)
	original = read(os.path.join(root, "STARTUP"))
	session, screen, off, on = enable_via_ui(root)
	check("UI: one item when disabled, four when enabled", (off, on) == (1, 4), (off, on))
	names = [entry[0] for entry in session.log]
	check("UI: setup, wait box, then the 'restart now?' question", names == ["MultiBootStartupMenuSetup", "MultiBootStartupMenuWait", "MessageBox"] and "Restart" in session.log[2][1][0], names)
	check("UI: the question is shown without going through Notifications", not notifications(), notifications())
	check("UI: wait box closed, question on top", [type(s).__name__ for s in session.stack] == ["MultiBootStartupMenuSetup", "MessageBox"]
		and session.stack[-1].text.startswith("The boot menu is active"), [type(s).__name__ for s in session.stack])
	conf = conf_of(root)
	check("enable: ENABLED=1 TIMEOUT=3 LAST=3", (conf["ENABLED"], conf["TIMEOUT"], conf["LAST"]) == ("1", "3", "3"), conf)
	check("enable: OSD and ALPHA copied", (conf["OSD"], conf["ALPHA"]) == ("0,720,0,576", "255"), conf)
	menu = read(os.path.join(root, "STARTUP"))
	check("enable: STARTUP is the menu line", menu == "kernel=/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs0 initrd=bootmenu/bootmenu.cpio.gz", menu)
	check("enable: previous STARTUP saved", read(os.path.join(root, "bootmenu", "STARTUP.before")) == original)
	bm = os.path.join(root, "bootmenu")
	check("enable: menu-init executable", os.access(os.path.join(bm, "menu-init"), os.X_OK))
	check("enable: 'never ran yet' marker set", os.path.exists(os.path.join(bm, ".unverified")))
	os.remove(os.path.join(bm, ".unverified"))  # as if the wrapper had run
	env = core.BootEnv(root)
	check("enable: installation complete", env.installation_problems() == [], env.installation_problems())
	menu_txt = read(os.path.join(bm, "frames", "menu.txt"))
	entries = [line for line in menu_txt.splitlines() if line.startswith("ENTRY=")]
	check("frames: 4 entries, the Recovery first", [e.split("|")[0] for e in entries] == ["ENTRY=0", "ENTRY=1", "ENTRY=2", "ENTRY=3"], entries)
	check("frames: the Recovery is also written as the fall-back target", "RECOVERY=STARTUP_RECOVERY|" in menu_txt, menu_txt)
	files = set(os.listdir(os.path.join(bm, "frames")))
	needed = {"item_%d.bmf" % i for i in range(4)} | {"boot_%d.bmf" % i for i in range(4)} | {"count_%d.bmf" % n for n in range(4)} | {"count_off.bmf", "boot_recovery.bmf", "idle.bmf", "error.bmf", "menu.txt"}
	check("frames: all files present", needed <= files, needed - files)
	check("frames: the countdown is its own area next to the title, not the footer", count_area(bm), count_area(bm))
	# answering "no" closes the setup
	session.stack[-1].close(False)
	enigma.run_timers()
	check("UI: setup closed after 'no'", screen.closed == ())


# ---------------------------------------------------------------------------
EVFMT = "<qqHHi" if struct.calcsize("P") == 8 else "<iiHHi"


def run_menu_init(root, keys=(), python=None, fb=True, wait=180):
	make_busybox_dir()
	for name in ("reboot.called", "STARTUP_ONCE"):
		try:
			os.remove(os.path.join(root, name))
		except OSError:
			pass
	shutil.rmtree(os.path.join(root, "run"), ignore_errors=True)
	os.makedirs(os.path.join(root, "run"))
	dev = os.path.join(root, "dev")
	shutil.rmtree(dev, ignore_errors=True)
	os.makedirs(os.path.join(dev, "input"))
	if fb:
		with open(os.path.join(dev, "fb0"), "wb") as f:
			f.truncate(1920 * 1080 * 4)
	fifo = os.path.join(dev, "input", "event0")
	os.mkfifo(fifo)
	writer = os.open(fifo, os.O_RDWR)
	env = dict(os.environ, MBSM_TESTROOT=root, MBSM_PYTHON=python or sys.executable, PATH=BB)

	def feed():
		for delay, code in keys:
			time.sleep(delay)
			for value in (1, 0):
				os.write(writer, struct.pack(EVFMT, 0, 0, 1, code, value))

	thread = threading.Thread(target=feed)
	thread.daemon = True
	started = time.time()
	proc = subprocess.Popen([os.path.join(BB, "sh"), os.path.join(PAYLOAD, "menu-init")], env=env)
	thread.start()
	try:
		rc = proc.wait(wait)
	except subprocess.TimeoutExpired:
		proc.kill()
		rc = "timeout"
	os.close(writer)
	return rc, time.time() - started


def expected_screen(root, index):
	buf = bytearray(1920 * 1080 * 4)
	for name in ("item_%d.bmf" % index, "boot_%d.bmf" % index):
		with open(os.path.join(root, "bootmenu", "frames", name), "rb") as f:
			data = f.read()
		x, y, w, h = (int.from_bytes(data[i:i + 2], "little") for i in (4, 6, 8, 10))
		pix = zlib.decompress(data[12:])
		for r in range(h):
			start = ((y + r) * 1920 + x) * 4
			buf[start:start + w * 4] = pix[r * w * 4:(r + 1) * w * 4]
	return bytes(buf)


def screen_is(root, index):
	with open(os.path.join(root, "dev", "fb0"), "rb") as f:
		return f.read() == expected_screen(root, index)


def log_of(root):
	return read(os.path.join(root, "bootmenu", "bootmenu.log"), "")


KEY_UP, KEY_DOWN, KEY_OK = 103, 108, 352
DIGIT = {0: 11, 1: 2, 2: 3, 3: 4, 7: 8}


def expect_boot(tag, root, slot, rc, entry_index=None, last=None):
	sf = "STARTUP_RECOVERY" if slot == 0 else "STARTUP_%d" % slot
	once = read(os.path.join(root, "STARTUP_ONCE"))
	check(tag + ": menu-init ended with a reboot", rc == 0 and read(os.path.join(root, "reboot.called"), "").startswith("REBOOT slot %d" % slot), (rc, read(os.path.join(root, "reboot.called")), log_of(root)[-1500:]))
	check(tag + ": STARTUP_ONCE = " + sf, once == read(os.path.join(root, sf)), once)
	check(tag + ": status OK", read(os.path.join(root, "bootmenu", "status"), "").strip() == "OK slot %d" % slot)
	check(tag + ": .running removed, .fails=0", not os.path.exists(os.path.join(root, "bootmenu", ".running")) and read(os.path.join(root, "bootmenu", ".fails"), "").strip() == "0")
	check(tag + ": STARTUP untouched", "initrd=bootmenu/" in read(os.path.join(root, "STARTUP")))
	if last is not None:
		check(tag + ": LAST=%s" % last, conf_of(root)["LAST"] == str(last), conf_of(root)["LAST"])
	if entry_index is not None:
		check(tag + ": screen shows entry %d + 'starting' footer" % entry_index, screen_is(root, entry_index))


def test_menu_stage(root):
	env = core.BootEnv(root)
	env.update_conf(VIDEOMODE="1080p50", RCCODE="3")

	rc, took = run_menu_init(root)
	expect_boot("countdown", root, 3, rc, entry_index=3, last=3)
	check("countdown: took about 3 s", 2.5 < took < 12, took)
	check("output: videomode written", read(os.path.join(root, "proc/stb/video/videomode")) == "1080p50\n")
	osd = [read(os.path.join(root, "proc/stb/fb", n)) for n in ("dst_left", "dst_width", "dst_top", "dst_height")]
	check("output: OSD position written like enigma2", osd == ["00000000\n", "000002D0\n", "00000000\n", "00000240\n"], osd)
	check("output: alpha written", read(os.path.join(root, "proc/stb/video/alpha")) == "255\n")
	check("remote control code written", read(os.path.join(root, "proc/stb/fp/remote_code")) == "3")

	rc, took = run_menu_init(root, keys=[(0.8, KEY_UP), (0.3, KEY_UP), (0.3, KEY_OK)])
	expect_boot("keys up,up,OK", root, 1, rc, entry_index=1, last=1)

	rc, took = run_menu_init(root, keys=[(0.8, DIGIT[2])])
	expect_boot("digit 2", root, 2, rc, entry_index=2, last=2)

	rc, took = run_menu_init(root, keys=[(0.8, DIGIT[7]), (0.3, KEY_DOWN), (0.3, KEY_DOWN), (0.3, KEY_OK)])
	expect_boot("digit 7 ignored, down,down,OK -> Recovery", root, 0, rc, entry_index=0, last=2)

	os.remove(os.path.join(root, "linuxrootfs1", "usr", "bin", "enigma2"))
	rc, took = run_menu_init(root, keys=[(0.8, DIGIT[1]), (3.2, DIGIT[3])])
	expect_boot("slot 1 without image refused, then 3", root, 3, rc, entry_index=3, last=3)
	check("slot 1 without image: logged as not bootable", "not bootable" in log_of(root))
	fakeboot.write(os.path.join(root, "linuxrootfs1", "usr", "bin", "enigma2"), b"ELF", 0o755)

	# countdown with a non bootable default: the Recovery starts, not another
	# slot, so that a boot that went wrong cannot be mistaken for a good one
	env.update_conf(LAST="2")
	os.rename(os.path.join(root, "linuxrootfs2"), os.path.join(root, "linuxrootfs2.x"))
	rc, took = run_menu_init(root)
	check("default not bootable at timeout: the Recovery starts, not another slot", rc == 0 and read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_RECOVERY")), log_of(root)[-800:])
	os.rename(os.path.join(root, "linuxrootfs2.x"), os.path.join(root, "linuxrootfs2"))
	env.update_conf(LAST="3")

	# --- fail-safe paths -------------------------------------------------
	fakeboot.write(os.path.join(root, "bootmenu", ".running"), "1\n")
	rc, took = run_menu_init(root)
	check("stale .running: default slot once", read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_3")))
	check("stale .running: .fails=1, status FAILSAFE, menu still enabled", read(os.path.join(root, "bootmenu", ".fails")).strip() == "1" and read(os.path.join(root, "bootmenu", "status")).startswith("FAILSAFE") and conf_of(root)["ENABLED"] == "1")
	check("stale .running: runner not started", "starting runner" not in log_of(root))

	rc, took = run_menu_init(root)
	expect_boot("success after one failure", root, 3, rc, last=3)

	fakeboot.write(os.path.join(root, "bootmenu", ".fails"), "1\n")
	fakeboot.write(os.path.join(root, "bootmenu", ".running"), "1\n")
	rc, took = run_menu_init(root)
	check("second consecutive failure: STARTUP <- STARTUP_3", read(os.path.join(root, "STARTUP")) == read(os.path.join(root, "STARTUP_3")))
	check("second consecutive failure: ENABLED=0, status DISABLED", conf_of(root)["ENABLED"] == "0" and read(os.path.join(root, "bootmenu", "status")).startswith("DISABLED"))
	check("second consecutive failure: no STARTUP_ONCE", not os.path.exists(os.path.join(root, "STARTUP_ONCE")))

	# re-enable for the next tests
	env.set_startup_menu()
	env.reset_failures()
	env.update_conf(ENABLED="1")

	os.rename(os.path.join(root, "bootmenu", "frames", "menu.txt"), os.path.join(root, "bootmenu", "frames", "menu.txt.x"))
	rc, took = run_menu_init(root)
	check("runner error (no menu.txt): fail-safe, default once", read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_3")) and read(os.path.join(root, "bootmenu", "status")).startswith("FAILSAFE"), log_of(root)[-800:])
	os.rename(os.path.join(root, "bootmenu", "frames", "menu.txt.x"), os.path.join(root, "bootmenu", "frames", "menu.txt"))
	env.reset_failures()

	if not QUICK:
		rc, took = run_menu_init(root, fb=False)
		check("no framebuffer: fail-safe after ~30 s", read(os.path.join(root, "bootmenu", "status"), "").startswith("FAILSAFE framebuffer") and 25 < took < 60, (took, log_of(root)[-500:]))
		env.reset_failures()

		hang = os.path.join(OUT, "hang.sh")
		fakeboot.write(hang, "#!/bin/sh\nsleep 1000\n", 0o755)
		rc, took = run_menu_init(root, python=hang, wait=240)
		check("hung runner: watchdog after ~60 s, fail-safe", read(os.path.join(root, "bootmenu", "status"), "").startswith("FAILSAFE menu runner") and 55 < took < 120, (took, log_of(root)[-500:]))
		subprocess.call(["pkill", "-f", "sleep 1000"])
		env.reset_failures()


# ---------------------------------------------------------------------------
def test_plugin_runtime(root):
	from MultiBootStartupMenu import glue
	import Tools.Multiboot as tm
	from Screens.MultiBootSelector import MultiBootSelector
	from Plugins.SystemPlugins.OBH.ImageManager import OpenBhImageManager
	env = core.BootEnv(root)

	# another image's selector replaced STARTUP; we are now in slot 2 (OBH with the plugin)
	plugin_env(root, current=2)
	shutil.copyfile(os.path.join(root, "STARTUP_2"), os.path.join(root, "STARTUP"))
	action = env.on_session_start(2)
	check("session start: STARTUP restored", action == "restored" and env.startup_is_menu(), action)
	check("session start: LAST=2", conf_of(root)["LAST"] == "2")

	check("session start: repair sets the 'never ran yet' marker", os.path.exists(os.path.join(root, "bootmenu", ".unverified")))
	# STARTUP changed again before the menu ever ran (e.g. USB rescue): no loop
	shutil.copyfile(os.path.join(root, "STARTUP_2"), os.path.join(root, "STARTUP"))
	action = env.on_session_start(2)
	check("session start: menu never ran -> disabled, not re-activated", action.startswith("disabled") and not env.startup_is_menu() and conf_of(root)["ENABLED"] == "0" and read(os.path.join(root, "bootmenu", "status")).startswith("NEVER_RAN"), action)
	notice = glue.pending_notice()
	check("session start: 'never ran' notice shown once", notice and "never started" in notice and glue.pending_notice() is None, notice)
	os.remove(os.path.join(root, "bootmenu", ".unverified"))
	env.reset_failures()
	env.update_conf(ENABLED="1")
	env.set_startup_menu()
	# broken installation: STARTUP must not be pointed at it
	shutil.copyfile(os.path.join(root, "STARTUP_2"), os.path.join(root, "STARTUP"))
	os.rename(os.path.join(root, "bootmenu", "bootmenu.cpio.gz"), os.path.join(root, "bootmenu", "x.gz"))
	action = env.on_session_start(2)
	check("session start: broken installation not re-activated", action.startswith("not restored") and not env.startup_is_menu(), action)
	os.rename(os.path.join(root, "bootmenu", "x.gz"), os.path.join(root, "bootmenu", "bootmenu.cpio.gz"))
	env.set_startup_menu()

	glue.install_patches()
	sel = MultiBootSelector(None)
	sel["config"] = type("C", (), {"getCurrent": lambda s: (("Slot 1", (1, 1)),)})()
	sel.reboot()
	check("patched selector: STARTUP_ONCE <- slot 1, reboot requested", read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_1")) and getattr(sel, "cancelled", None) == 2 and conf_of(root)["LAST"] == "1")
	check("patched selector: STARTUP still the menu", env.startup_is_menu())

	im = OpenBhImageManager()
	im.multibootslot = 2
	im.session = FakeSession()
	im.FlashQuestion(True)
	check("patched ImageManager: STARTUP_ONCE <- slot 2 after flashing", read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_2")) and im.session.log[0][0] == "TryQuitMainloop")
	im.FlashQuestion(False)
	check("patched ImageManager: 'no' keeps the original behaviour", getattr(im, "flash", None) == ("original", False))

	got = []
	tm.activateSlot("3", "", lambda *a: got.append(a))
	check("patched activateSlot (OpenWebif): STARTUP_ONCE <- slot 3", got == [(0, 0)] and read(os.path.join(root, "STARTUP_ONCE")) == read(os.path.join(root, "STARTUP_3")))

	# notices
	fakeboot.write(os.path.join(root, "bootmenu", "status"), "FAILSAFE framebuffer /dev/fb0 did not appear\n")
	first = glue.pending_notice()
	second = glue.pending_notice()
	check("notice shown once after a fail-safe boot", first and "default image" in first and second is None, (first, second))

	# plugin update: payload reinstalled; renamed image: frames re-rendered
	env.update_conf(VERSION="0.0.9")
	sig_before = env.frames_signature()
	tm.IMAGES[1] = {"imagename": "OpenPLi 9.2 (01-10-2026)"}
	result = glue.refresh_if_needed()
	check("refresh: payload and frames updated", "payload" in result and "frames" in result and conf_of(root)["VERSION"] == core.VERSION, result)
	check("refresh: new signature, initrd checksum valid", env.frames_signature() != sig_before and env.installation_problems() == [], env.installation_problems())
	check("refresh: second run does nothing", glue.refresh_if_needed() == "up to date")
	with open(os.path.join(root, "STARTUP.cpio.gz"), "ab") as f:
		f.write(b"")
	import gzip as _gz
	raw = _gz.decompress(open(os.path.join(root, "STARTUP.cpio.gz"), "rb").read())
	with open(os.path.join(root, "STARTUP.cpio.gz"), "wb") as f:
		f.write(_gz.compress(raw, compresslevel=6, mtime=1))
	result = glue.refresh_if_needed()
	check("refresh: changed STARTUP.cpio.gz -> initrd rebuilt", "rebuilt" in result and env.installation_problems() == [] and conf_of(root)["SOURCE_MD5"] == env.source_md5(), result)
	env.update_conf(VERSION="9.9.9")
	check("refresh: older plugin leaves a newer installation alone", "newer version" in glue.refresh_if_needed())
	env.update_conf(VERSION=core.VERSION)

	# disable from the UI (default image = last started)
	from MultiBootStartupMenu.ui import MultiBootStartupMenuSetup
	plugin_env(root, current=3)
	session = FakeSession()
	screen = session.open(MultiBootStartupMenuSetup)
	screen.cfgEnabled.value = False
	screen.createSetup()
	screen.keySave()
	check("disable: STARTUP <- STARTUP_3 (current slot)", read(os.path.join(root, "STARTUP")) == read(os.path.join(root, "STARTUP_3")))
	check("disable: ENABLED=0", conf_of(root)["ENABLED"] == "0")
	check("disable: message shown", session.log and "disabled" in session.log[-1][1][0])
	check("disabled: session start changes nothing", env.on_session_start(3) is None and not env.startup_is_menu())


# ---------------------------------------------------------------------------
def test_wrapper(root):
	"""Runs the initrd /init in a chroot with host busybox and stubbed mount/switch_root."""
	jail = os.path.join(OUT, "jail")
	shutil.rmtree(jail, ignore_errors=True)
	for d in ("bin", "sbin", "proc/sys/kernel", "sys", "dev", "newroot/bootmenu", "newroot/bin"):
		os.makedirs(os.path.join(jail, d))
	shutil.copy(shutil.which("busybox"), os.path.join(jail, "bin", "busybox"))
	subprocess.check_call(["chroot", jail, "/bin/busybox", "--install", "-s", "/bin"])
	for name in ("mount", "umount", "mdev", "switch_root"):
		os.remove(os.path.join(jail, "bin", name))
		fakeboot.write(os.path.join(jail, "sbin", name), '#!/bin/sh\necho "%s $*" >> /calls\n[ -f /fail_%s ] && exit 1\nexit 0\n' % (name, name), 0o755)
	fakeboot.write(os.path.join(jail, "init.stage2"), '#!/bin/sh\necho STAGE2 >> /calls\n', 0o755)
	fakeboot.write(os.path.join(jail, "init"), read(os.path.join(PAYLOAD, "init")), 0o755)
	fakeboot.write(os.path.join(jail, "proc", "cmdline"), "rootfstype=ext4 rootwait rw root=/dev/mmcblk0p4 bmem=630m@394m\n")
	subprocess.check_call(["mknod", os.path.join(jail, "dev", "mmcblk0p4"), "b", "179", "4"])
	os.symlink("/bin/busybox", os.path.join(jail, "newroot", "bin", "sh"))
	nr = os.path.join(jail, "newroot", "bootmenu")

	def run(setup):
		for f in ("calls", "newroot/bootmenu/.wrapper_pending", "newroot/bootmenu/status", "fail_mount"):
			try:
				os.remove(os.path.join(jail, f))
			except OSError:
				pass
		setup()
		subprocess.call(["chroot", jail, "/bin/sh", "/init"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
		return read(os.path.join(jail, "calls"), "")

	def enabled():
		fakeboot.write(os.path.join(nr, "menu-init"), "#!/bin/sh\n", 0o755)
		fakeboot.write(os.path.join(nr, "bootmenu.conf"), "ENABLED=1\n")

	calls = run(enabled)
	check("wrapper: enabled -> switch_root /newroot /bootmenu/menu-init", "switch_root /newroot /bootmenu/menu-init" in calls and "STAGE2" not in calls, calls)
	check("wrapper: devtmpfs mounted on /newroot/dev", "mount -n -t devtmpfs devtmpfs /newroot/dev" in calls, calls)
	check("wrapper: hand-over marker written", os.path.exists(os.path.join(nr, ".wrapper_pending")))
	check("wrapper: panic reboot armed", read(os.path.join(jail, "proc/sys/kernel/panic")) == "10\n")

	def unverified():
		enabled()
		fakeboot.write(os.path.join(nr, ".unverified"), "1\n")
	calls = run(unverified)
	check("wrapper: removes the 'never ran yet' marker", not os.path.exists(os.path.join(nr, ".unverified")) and "switch_root" in calls)

	def pending():
		enabled()
		fakeboot.write(os.path.join(nr, ".wrapper_pending"), "1\n")
	calls = run(pending)
	check("wrapper: failed previous hand-over -> original stage 2", "STAGE2" in calls and "switch_root" not in calls and read(os.path.join(nr, "status"), "").startswith("WRAPPER_FAILED"), calls)
	check("wrapper: marker cleared after the fallback", not os.path.exists(os.path.join(nr, ".wrapper_pending")))

	def trial():
		enabled()
		fakeboot.write(os.path.join(nr, "bootmenu.conf"), "ENABLED=once\n")
	calls = run(trial)
	check("wrapper: a single trial (ENABLED=once) is loaded like the real thing", "switch_root /newroot /bootmenu/menu-init" in calls and "STAGE2" not in calls, calls)

	def disabled():
		enabled()
		fakeboot.write(os.path.join(nr, "bootmenu.conf"), "ENABLED=0\n")
	calls = run(disabled)
	check("wrapper: disabled -> original stage 2", "STAGE2" in calls and "switch_root" not in calls, calls)

	def half():
		enabled()
		fakeboot.write(os.path.join(nr, "bootmenu.conf"), "ENABLED=onceupon\n")
	calls = run(half)
	check("wrapper: only the exact words 1 and once count", "STAGE2" in calls and "switch_root" not in calls, calls)

	def missing():
		enabled()
		os.remove(os.path.join(nr, "menu-init"))
	calls = run(missing)
	check("wrapper: menu-init missing -> original stage 2", "STAGE2" in calls and "switch_root" not in calls, calls)

	def nomount():
		enabled()
		fakeboot.write(os.path.join(jail, "fail_mount"), "")
	calls = run(nomount)
	check("wrapper: root not mountable -> original stage 2", "STAGE2" in calls and "switch_root" not in calls, calls)


# ---------------------------------------------------------------------------
def test_dialogs(root):
	"""The three things that went wrong in 0.1.0 and 0.2.0: a dialog opened
	right after closing another one, a message that arrived only after
	leaving every menu, and RED claiming there was something unsaved."""
	from MultiBootStartupMenu.ui import MultiBootStartupMenuSetup, MultiBootStartupMenuPreview, MultiBootStartupMenuWait
	from Screens.MessageBox import MessageBox
	fakeboot.build(root)
	plugin_env(root)

	# the model must really refuse what enigma2 refuses, or nothing below means anything
	probe = FakeSession()
	setup = probe.open(MultiBootStartupMenuSetup)
	box = probe.open(MessageBox, "x")
	probe.close(box)
	try:
		probe.open(MessageBox, "y")
		raised = False
	except RuntimeError:
		raised = True
	check("session model: open right after close raises, like enigma2", raised)
	enigma.run_timers()
	setup.close()
	enigma.run_timers()

	# enable: wait box, then the question, with nothing queued
	del notifications()[:]
	session, screen, off, on = enable_via_ui(root)
	opened = [entry[0] for entry in session.log]
	check("dialogs: wait box and question opened, nothing queued", opened == ["MultiBootStartupMenuSetup", "MultiBootStartupMenuWait", "MessageBox"] and not notifications(), (opened, notifications()))
	question = session.stack[-1]

	# RED after a save: one confirmation, and no "not saved" warning
	question.close(False)
	enigma.run_timers()
	session2 = FakeSession()
	screen2 = session2.open(MultiBootStartupMenuSetup)
	screen2.cfgTimeout.value = "20"
	screen2.saved = True  # as right after a save
	screen2.keyCancel()
	enigma.run_timers()
	texts = [entry[1][0] for entry in session2.log if entry[0] == "MessageBox"]
	check("RED after a save: one question, no 'not saved' warning", len(texts) == 1 and "not been saved" not in texts[0], texts)
	check("RED: 'no' keeps the plugin open", (session2.stack[-1].close(False), enigma.run_timers(), screen2.closed)[2] is None, screen2.closed)
	screen2.keyCancel()
	enigma.run_timers()
	session2.stack[-1].close(True)
	enigma.run_timers()
	check("RED: 'yes' leaves the plugin", screen2.closed == ())

	# the Recovery can be the default image, and the preview is on two keys
	session5 = FakeSession()
	screen5 = session5.open(MultiBootStartupMenuSetup)
	screen5.cfgEnabled.value = True
	screen5.createSetup()
	keys = [key for key, text in screen5.cfgDefault.choices.choices]
	check("default image: the Recovery is among the choices, first", keys == ["last", "0", "1", "2", "3"], keys)
	screen5.cfgDefault.value = "0"
	screen5.cfgRecovery.value = False
	screen5.createSetup()
	keys = [key for key, text in screen5.cfgDefault.choices.choices]
	check("default image: hiding the Recovery removes it from the choices", keys == ["last", "1", "2", "3"] and screen5.cfgDefault.value == "last", (keys, screen5.cfgDefault.value))
	screen5.cfgRecovery.value = True
	screen5.createSetup()
	helptext = [item[2] for item in screen5.list if item[1] is screen5.cfgRecovery][0]
	check("default image: the help says which Recovery was found", "OpenBh" in helptext or "Recovery" in helptext, helptext)
	colors = screen5["mbsmColorActions"]
	check("colour keys: blue = preview, yellow = try once, nothing else",
		colors.actions == {"blue": screen5.keyPreview, "yellow": screen5.keyTryOnce}, sorted(colors.actions))
	check("preview: the blue button is labelled", screen5["key_blue"].text == "Preview", screen5["key_blue"].text)
	check("try once: the yellow button is labelled", screen5["key_yellow"].text == "Try once", screen5["key_yellow"].text)

	# preview: opened, not queued
	import Tools.LoadPixmap as lp
	from PIL import Image
	del notifications()[:]
	session3 = FakeSession()
	screen3 = session3.open(MultiBootStartupMenuSetup)
	screen3.keyPreview()
	enigma.run_timers()
	opened = [entry[0] for entry in session3.log]
	check("preview: shown at once, not queued", opened == ["MultiBootStartupMenuSetup", "MultiBootStartupMenuWait", "MultiBootStartupMenuPreview"] and not notifications(), (opened, notifications()))
	path = session3.log[-1][1][0]
	check("preview: image written", os.path.isfile(path))
	check("preview: image has the size of the screen", Image.open(path).size == (1920, 1080), Image.open(path).size)
	check("preview: the wait box is not a MessageBox the user could dismiss", not issubclass(MultiBootStartupMenuWait, MessageBox))

	def show_preview(working=True, result=0):
		lp.WORKING = working
		enigma.ePicLoad.RESULT = result
		session4 = FakeSession()
		setup4 = session4.open(MultiBootStartupMenuSetup)
		view = session4.openWithCallback(setup4.previewClosed, MultiBootStartupMenuPreview, path)
		for fnc in view.onLayoutFinish:
			fnc()
		enigma.run_timers()
		lp.WORKING, enigma.ePicLoad.RESULT = True, 0
		return session4, view

	session4, view = show_preview()
	check("preview: picture on screen with LoadPixmap", view["preview"].instance.pixmap is not None and view.closed is None)

	session4, view = show_preview(working=False)
	check("preview: falls back to the decoder when LoadPixmap gives nothing", view["preview"].instance.pixmap is not None and view.closed is None)
	check("preview: setPara called with a list, as enigma2 requires", isinstance(view.picload.para, list) and view.picload.para[0] == 1920, view.picload.para)

	session4, view = show_preview(working=False, result=3)
	texts = [entry[1][0] for entry in session4.log if entry[0] == "MessageBox"]
	check("preview: a decoder error is reported, not a black screen", texts and "could not be shown" in texts[-1], texts)


# ---------------------------------------------------------------------------
def test_fallback(root):
	"""The Recovery is the fall-back of the countdown even when it is not in
	the list: hiding it is a matter of taste, the safety net is not."""
	import importlib.util
	spec = importlib.util.spec_from_file_location("mbsm_runner", os.path.join(PAYLOAD, "runner.py"))
	runner = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(runner)
	menu = runner.Menu.__new__(runner.Menu)
	menu.entries = [(1, "STARTUP_1", "Slot 1"), (3, "STARTUP_3", "Slot 3")]
	menu.recovery = (0, "STARTUP_RECOVERY", "Recovery")
	check("fall-back: the hidden Recovery comes right after the chosen image", menu.auto_order(1) == [1, runner.Menu.RECOVERY, 0], menu.auto_order(1))
	menu.recovery = None
	check("fall-back: with no Recovery at all the other slots are tried", menu.auto_order(1) == [1, 0], menu.auto_order(1))
	menu.entries = [(0, "STARTUP_RECOVERY", "Recovery"), (1, "STARTUP_1", "Slot 1"), (3, "STARTUP_3", "Slot 3")]
	menu.recovery = (0, "STARTUP_RECOVERY", "Recovery")
	check("fall-back: a Recovery that is in the list is used as a normal entry", menu.auto_order(2) == [2, 0, 1], menu.auto_order(2))

	from MultiBootStartupMenu import glue
	folder = os.path.join(OUT, "frames_hidden")
	shutil.rmtree(folder, ignore_errors=True)
	entries = [{"slot": 1, "startup": "STARTUP_1", "label": "Slot 1", "name": "image", "tag": ""}]
	render.MenuRenderer(entries, glue.menu_strings(), "", timeout=3).write_all(folder, 3, "sig", ("STARTUP_RECOVERY", "Recovery"))
	menu_txt = read(os.path.join(folder, "menu.txt"), "")
	check("frames: hidden Recovery still written as the fall-back", "RECOVERY=STARTUP_RECOVERY|Recovery" in menu_txt and "ENTRY=0" not in menu_txt, menu_txt)
	check("frames: the 'starting the Recovery' footer is rendered too", os.path.isfile(os.path.join(folder, "boot_recovery.bmf")))


# ---------------------------------------------------------------------------
def test_untested_receiver(root):
	"""A receiver nobody has tested: the plugin shows itself and says so, but
	does nothing until the user accepts it - and offers the trial instead."""
	from MultiBootStartupMenu import core as c, glue
	from MultiBootStartupMenu.ui import MultiBootStartupMenuSetup
	import Components.SystemInfo as si

	fakeboot.build(root)
	plugin_env(root)
	original = read(os.path.join(root, "STARTUP"))
	real_model = si.MODEL
	si.MODEL = glue.MODEL = "zgemmah9combo"  # anything outside SUPPORTED_MODELS
	try:
		check("untested: the plugin is still available (the boot layout is what counts)", glue.is_available())
		check("untested: but it is not a tested receiver", not glue.is_tested())

		session = FakeSession()
		screen = session.open(MultiBootStartupMenuSetup)
		check("untested: an extra 'accept' entry comes first", len(screen.list) == 2 and screen.list[0][1] is screen.cfgUntested, len(screen.list))
		check("untested: the warning names the receiver and the trial", "not been tested" in screen.list[0][2] and "YELLOW" in screen.list[0][2])
		check("untested: the warning carries the line to photograph, with the model string",
			"photograph" in screen.list[0][2] and "zgemmah9combo" in screen.list[0][2] and "untested" in screen.list[0][2], screen.list[0][2])

		screen.cfgEnabled.value = True
		screen.cfgTimeout.value = "3"
		screen.createSetup()
		screen.keySave()
		enigma.run_timers()
		texts = [entry[1][0] for entry in session.log if entry[0] == "MessageBox"]
		check("untested: GREEN refuses until it is accepted", texts and "has not been tested" in texts[-1], texts)
		check("untested: nothing was changed", read(os.path.join(root, "STARTUP")) == original and conf_of(root)["ENABLED"] == "0")

		# the trial: STARTUP_ONCE only
		screen.keyTryOnce()
		enigma.run_timers()
		screen.tryOnceAnswer(True)
		enigma.run_timers()
		conf = conf_of(root)
		once = read(os.path.join(root, "STARTUP_ONCE"), "")
		check("try once: STARTUP is not touched", read(os.path.join(root, "STARTUP")) == original, read(os.path.join(root, "STARTUP")))
		check("try once: STARTUP_ONCE is the menu line", once == "kernel=/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs0 initrd=bootmenu/bootmenu.cpio.gz", once)
		check("try once: ENABLED=once, TRIAL=pending", (conf["ENABLED"], conf["TRIAL"]) == ("once", "pending"), conf)
		check("try once: the receiver is recorded", conf["UNTESTED"] == "1" and conf["MODEL"], conf["MODEL"])
		check("try once: the 'never ran yet' marker is set", os.path.exists(os.path.join(root, "bootmenu", ".unverified")))
		check("try once: the menu is not treated as enabled meanwhile", not glue.menu_enabled())

		env = c.BootEnv(root)
		bm = os.path.join(root, "bootmenu")

		# 1. the trial never ran: the marker is still there
		check("trial outcome: marker still there -> the initrd was never loaded", env.trial_outcome() == "initrd")
		# 2. the wrapper ran but the menu stage gave up
		os.remove(os.path.join(bm, ".unverified"))
		fakeboot.write(os.path.join(bm, "status"), "FAILSAFE framebuffer /dev/fb0 did not appear\n")
		check("trial outcome: loaded but no menu -> 'menu'", env.trial_outcome() == "menu")
		# 3. it all worked
		fakeboot.write(os.path.join(bm, "status"), "OK slot 3\n")
		check("trial outcome: a slot was chosen -> 'ran'", env.trial_outcome() == "ran")

		action = env.on_session_start(3)
		conf = conf_of(root)
		check("trial: one boot only, whatever happened", (conf["ENABLED"], conf["TRIAL"]) == ("0", "ran"), conf)
		check("trial: an unused STARTUP_ONCE is removed", not os.path.exists(os.path.join(root, "STARTUP_ONCE")), action)
		check("trial: STARTUP was never touched", read(os.path.join(root, "STARTUP")) == original)
		check("trial: the result is reported to the user", "worked" in (glue.trial_notice("ran") or ""), glue.trial_notice("ran"))
		check("trial: a receiver that ignored it is told so", "not loaded at all" in (glue.trial_notice("initrd") or ""))
		# someone who never opens a terminal has to be able to report by
		# photographing the screen: the line has to carry the model string
		notice = glue.trial_notice("ran") or ""
		check("trial: the message carries the line to photograph", "photograph" in notice and glue.report_line() in notice, notice)
		line = glue.report_line()
		check("report line: model string, image, layout, tested, trial",
			line.startswith("MBSM ") and "zgemmah9combo" in line and "boot OK" in line and "untested" in line and "trial ran" in line, line)
		check("trial: the message also names the file to copy", glue.REPORT_FILE in notice, notice)

		# the same thing as a file, for whoever would rather copy than photograph
		target = os.path.join(OUT, "receiver-model.txt")
		written = glue.write_report_file(target)
		body = read(target, "")
		check("report file: written where asked", written == target and body)
		check("report file: the line comes first, the detail after",
			body.startswith(line) and "model: zgemmah9combo" in body and "Recovery problems" in body, body[:120])
		check("report file: /tmp/receiver-model.txt by default", glue.REPORT_FILE == "/tmp/receiver-model.txt", glue.REPORT_FILE)

		# a trial on top of a menu that is already permanent would end with
		# ENABLED=0 and STARTUP still pointing at the menu, i.e. booting the
		# Recovery at every start: refused, at both levels
		fakeboot.write(os.path.join(root, "STARTUP"), read(os.path.join(root, "STARTUP_RECOVERY")) + " initrd=bootmenu/bootmenu.cpio.gz")
		env.update_conf(ENABLED="1")
		check("try once: refused while the menu is already permanent", env.startup_is_menu())
		try:
			env.try_once({})
			refused = False
		except c.BootMenuError as err:
			refused = "nothing to try" in str(err)
		check("try once: core refuses it", refused)
		session = FakeSession()
		screen = session.open(MultiBootStartupMenuSetup)
		screen.keyTryOnce()
		enigma.run_timers()
		texts = [entry[1][0] for entry in session.log if entry[0] == "MessageBox"]
		check("try once: the screen says why instead", texts and "nothing to try" in texts[-1], texts)
		check("try once: no trial was left pending", conf_of(root)["ENABLED"] == "1" and not os.path.exists(os.path.join(root, "STARTUP_ONCE")))
		fakeboot.write(os.path.join(root, "STARTUP"), original)
		env.update_conf(ENABLED="0")

		# accepting makes GREEN work, without the Vu+ driver check
		shutil.rmtree(os.path.join(root, "etc"), ignore_errors=True)
		shutil.rmtree(os.path.join(root, "lib"), ignore_errors=True)
		check("untested: the Vu+ driver check would stop it", env.recovery_problems(True) and not env.recovery_problems(False))
		session = FakeSession()
		screen = session.open(MultiBootStartupMenuSetup)
		screen.cfgUntested.value = True
		screen.cfgEnabled.value = True
		screen.cfgTimeout.value = "3"
		screen.createSetup()
		screen.keySave()
		enigma.run_timers()
		check("untested: once accepted, GREEN enables the menu", conf_of(root)["ENABLED"] == "1" and c.BootEnv(root).startup_is_menu(), conf_of(root)["ENABLED"])
		check("untested: the choice is remembered, so it is not asked again", conf_of(root)["UNTESTED"] == "1")
	finally:
		si.MODEL = glue.MODEL = real_model
		core.BOOT = root

	# a tested receiver is left exactly as it was
	fakeboot.build(root)
	plugin_env(root)
	session = FakeSession()
	screen = session.open(MultiBootStartupMenuSetup)
	check("tested receiver: no extra entry, nothing to accept", len(screen.list) == 1 and screen.tested)

	# a receiver without the layout: the plugin does not register at all, so
	# the only thing it can leave behind is the line saying why
	from MultiBootStartupMenu import plugin
	import io
	import contextlib
	empty = os.path.join(OUT, "noboot")
	shutil.rmtree(empty, ignore_errors=True)
	os.makedirs(empty)
	core.BOOT = empty
	try:
		out = io.StringIO()
		with contextlib.redirect_stdout(out):
			descriptors = plugin.Plugins()
		said = out.getvalue()
		check("no layout: the plugin registers nothing", descriptors == [], descriptors)
		check("no layout: it still says why, with the model string", "not active here" in said and "model=" in said and "STARTUP" in said, said.strip())
	finally:
		core.BOOT = root
		plugin_env(root)


def main():
	root = os.path.join(OUT, "boot")
	test_plugin_enable(root)
	test_menu_stage(root)
	test_plugin_runtime(root)
	test_untested_receiver(root)
	test_wrapper(root)
	test_dialogs(root)  # last: it rebuilds the fake boot partition
	test_fallback(root)
	failed = [r for r in RESULTS if not r[1]]
	print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
	for name, ok, detail in failed:
		print("FAILED:", name, detail)
	sys.exit(1 if failed else 0)


if __name__ == "__main__":
	main()
