import os
SCOPE_PLUGINS = "plugins"


def resolveFilename(scope, path=""):
	return os.path.join(os.environ.get("MBSM_PLUGINS", "/tmp"), path)
