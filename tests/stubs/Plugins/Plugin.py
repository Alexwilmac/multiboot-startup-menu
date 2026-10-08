class PluginDescriptor:
	WHERE_PLUGINMENU, WHERE_MENU, WHERE_SESSIONSTART = 3, 5, 8

	def __init__(self, **kw):
		self.__dict__.update(kw)
