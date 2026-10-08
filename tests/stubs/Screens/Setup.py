from Screens.Screen import Screen


class _List:
	def __init__(self):
		self.list = []


class Setup(Screen):
	def __init__(self, session, setup=None, plugin=None, PluginLanguageDomain=None, yellow_button=None, blue_button=None, *a, **k):
		Screen.__init__(self, session)
		self["config"] = _List()
		self.yellow = yellow_button
		self.createSetup()
