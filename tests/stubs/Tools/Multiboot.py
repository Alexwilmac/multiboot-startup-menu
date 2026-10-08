IMAGES = {}


def GetImagelist(Recovery=None):
	return dict(IMAGES)


def createInfo(slot, imagedir="/"):
	return "OpenBh 5.6.018 (01-05-2026)"


def activateSlot(slotCode, bootCode, callback):
	callback("original", 0)
