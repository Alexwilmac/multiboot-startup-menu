from Screens.Standby import QUIT_REBOOT
from Screens.Screen import Screen


class MultiBootSelector(Screen):
	def reboot(self):
		self.rebooted = "original"

	def cancel(self, value=None):
		self.cancelled = value
