NOTIFICATIONS = []


def AddNotification(screen, *args, **kwargs):
	NOTIFICATIONS.append((screen, args, kwargs))


def AddNotificationWithCallback(fnc, screen, *args, **kwargs):
	NOTIFICATIONS.append((screen, args, kwargs))
