# minimal enigma stub for off-box tests
import time

TIMERS = []


class eTimer:
	"""The interval matters: a watchdog of a few minutes must not fire in the
	same round as a poll timer of 250 ms."""

	def __init__(self):
		self.callback = []
		self.active = False
		self.single = False
		self.interval = 0.0
		self.due = 0.0
		TIMERS.append(self)

	def start(self, ms, single=False):
		self.active = True
		self.single = single
		self.interval = ms / 1000.0
		self.due = time.monotonic() + self.interval

	def stop(self):
		self.active = False

	def fire_if_due(self, now):
		if not self.active or now < self.due:
			return False
		if self.single:
			self.active = False
		else:
			self.due = now + self.interval
		for cb in list(self.callback):
			cb()
		return True


def run_timers(rounds=2000, sleep=0.02, horizon=1.0):
	"""Run the timers until only long-term ones (watchdogs) are left."""
	for _ in range(rounds):
		now = time.monotonic()
		for t in list(TIMERS):
			t.fire_if_due(now)
		now = time.monotonic()
		if not [t for t in TIMERS if t.active and t.due <= now + horizon]:
			return
		time.sleep(sleep)


class _Size:
	def __init__(self, w, h):
		self._w, self._h = w, h

	def width(self):
		return self._w

	def height(self):
		return self._h


class _Desktop:
	def size(self):
		return _Size(1920, 1080)


def getDesktop(n):
	return _Desktop()


def loadPNG(path):
	return None


class ePicLoad:
	"""Models the real one closely enough for the fallback path: setPara()
	only accepts a list, and the data arrives through the callback."""

	ACCEPTS_TUPLE = False
	RESULT = 0

	def __init__(self):
		self.callbacks = []
		self.para = None
		self.path = None
		self.PictureData = type("S", (), {"get": lambda s: self.callbacks})()

	def setPara(self, para):
		if isinstance(para, list) or ePicLoad.ACCEPTS_TUPLE:
			self.para = list(para)

	def startDecode(self, path):
		self.path = path
		if ePicLoad.RESULT:
			return ePicLoad.RESULT
		if not self.para or not self.para[0] or not self.para[1]:
			return 0  # accepted, but it will never call back: a black screen
		for cb in list(self.callbacks):
			cb("")
		return 0

	def getData(self):
		from Tools.LoadPixmap import _Ptr
		return _Ptr(self.path) if self.para else None
