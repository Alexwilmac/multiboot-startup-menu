class _Size:
	def __init__(self, w, h):
		self._w, self._h = w, h

	def width(self):
		return self._w

	def height(self):
		return self._h


class _Instance:
	"""Behaves like ePixmap: setPixmap() refuses anything but a gPixmap."""

	def __init__(self):
		self.pixmap = None
		self.scale = 0

	def setScale(self, value):
		self.scale = value

	def size(self):
		return _Size(1920, 1080)

	def setPixmap(self, pixmap):
		if not getattr(pixmap, "is_pixmap", False):
			raise TypeError("argument 2 must be gPixmap, not %s" % type(pixmap).__name__)
		self.pixmap = pixmap


class Pixmap:
	def __init__(self):
		self.instance = _Instance()
