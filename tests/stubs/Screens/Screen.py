class Screen(dict):
	def __init__(self, session, *a, **k):
		dict.__init__(self)
		self.session = session
		self.onLayoutFinish = []
		self.onClose = []
		self.closed = None

	def close(self, *args):
		self.closed = args
		if self.session:
			self.session.close(self, *args)

	def doClose(self):
		for fnc in self.onClose:
			fnc()

	def setTitle(self, t):
		self.title = t
