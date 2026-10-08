import os

# the tests switch this to model a box where LoadPixmap does not work
WORKING = True


class _Pixmap:
	is_pixmap = True

	def __init__(self, path):
		self.path = path


class _Ptr:
	"""Like the ePtr enigma2 returns: the pixmap itself is behind __deref__()."""

	def __init__(self, path):
		self.path = path

	def __deref__(self):
		return _Pixmap(self.path)


def LoadPixmap(path, desktop=None, cached=None):
	if not WORKING or not os.path.isfile(path):
		return None
	return _Ptr(path)
