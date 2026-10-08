QUIT_REBOOT = 2


class TryQuitMainloop:
	def __init__(self, session, retvalue=1, *a, **k):
		self.retvalue = retvalue
