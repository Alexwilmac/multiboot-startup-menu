class _ChoicesList:
	"""Like enigma2's choicesList: the pairs live in .choices."""

	def __init__(self, choices=None):
		self.choices = list(choices or [])

	def __iter__(self):
		return iter(self.choices)

	def __len__(self):
		return len(self.choices)


class _Cfg:
	def __init__(self, default=None, choices=None):
		self.value = default
		self.default = default
		self.choices = choices


class ConfigYesNo(_Cfg):
	pass


class ConfigSelection(_Cfg):
	def __init__(self, default=None, choices=None):
		_Cfg.__init__(self, default, _ChoicesList(choices))

	def setChoices(self, choices, default=None):
		self.choices = _ChoicesList(choices)
		keys = [key for key, text in self.choices.choices]
		if default is not None:
			self.default = default
		if self.value not in keys:
			self.value = self.default if self.default in keys else (keys[0] if keys else None)


def NoSave(x):
	return x


class _N:
	pass


config = _N()
config.osd = _N()
config.osd.dst_left = _Cfg(0)
config.osd.dst_width = _Cfg(720)
config.osd.dst_top = _Cfg(0)
config.osd.dst_height = _Cfg(576)
config.osd.alpha = _Cfg(255)
