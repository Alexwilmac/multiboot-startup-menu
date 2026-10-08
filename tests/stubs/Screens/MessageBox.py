from Screens.Screen import Screen


class MessageBox(Screen):
	TYPE_YESNO, TYPE_INFO, TYPE_WARNING, TYPE_ERROR = 0, 1, 2, 3

	def __init__(self, session, text, type=0, timeout=0, default=True, enable_input=True, **kw):
		Screen.__init__(self, session)
		self.text = text
		self.type = type
