# Builds enigma2-plugin-systemplugins-multibootstartupmenu_<version>_all.ipk
import io
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SRC = os.path.join(PROJECT, "src", "MultiBootStartupMenu")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJECT, "src"))
sys.path.insert(0, os.path.join(PROJECT, "tests", "stubs"))
from MultiBootStartupMenu.core import VERSION  # noqa: E402

# Edit these two lines before publishing the package.
MAINTAINER = "AlexWilMac"
HOMEPAGE = "https://github.com/AlexWilMac/multiboot-startup-menu"

PACKAGE = "enigma2-plugin-systemplugins-multibootstartupmenu"
OLD_PACKAGE = "enigma2-plugin-systemplugins-kexecbootmenu"  # the name used up to 0.3.3
TARGET = "usr/lib/enigma2/python/Plugins/SystemPlugins/MultiBootStartupMenu"
EXEC = {"payload/init", "payload/menu-init"}
MTIME = int(time.time())

CONTROL = """Package: %s
Version: %s
Description: Boot menu for the Vu+ kexec MultiBoot (OpenBH)
 Shows the list of the MultiBoot slots at every start of a Vu+ Ultimo4K
 and boots the one chosen with the remote control.
Section: extra
Priority: optional
Maintainer: %s
License: GPL-2.0-only
Architecture: all
Source: MultiBootStartupMenu
Conflicts: %s
Replaces: %s
Provides: %s
""" % (PACKAGE, VERSION, MAINTAINER, OLD_PACKAGE, OLD_PACKAGE, OLD_PACKAGE)
if HOMEPAGE:
	CONTROL += "Homepage: %s\n" % HOMEPAGE

POSTINST = """#!/bin/sh
echo "MultiBootStartupMenu %s installed."
if opkg list-installed 2>/dev/null | grep -q '^%s '; then
	echo
	echo "WARNING: the previous package is still installed and would run beside this one."
	echo "         Remove it now:  opkg remove %s"
	echo "         (that restores /boot/STARTUP to the running slot and turns the menu off;"
	echo "          switch it on again from the plugin afterwards)"
fi
echo "Restart the GUI, then: Menu > Standby & Restart > MultiBoot startup menu."
exit 0
""" % (VERSION, OLD_PACKAGE, OLD_PACKAGE)

PRERM = r"""#!/bin/sh
# On removal: if the boot menu is active, boot the current slot directly again.
[ "$1" = "remove" ] || exit 0
CONF=/boot/bootmenu/bootmenu.conf
grep -q '^ENABLED=1' $CONF 2>/dev/null || exit 0
grep -q 'initrd=bootmenu/' /boot/STARTUP 2>/dev/null || exit 0
N=$(sed -n 's/.*rootsubdir=[^ ]*linuxrootfs\([0-9][0-9]*\).*/\1/p' /proc/cmdline | head -n 1)
if [ -n "$N" ] && [ "$N" != 0 ] && [ -f /boot/STARTUP_$N ]; then
	cp -f /boot/STARTUP_$N /boot/STARTUP.tmp && sync && mv -f /boot/STARTUP.tmp /boot/STARTUP && sync
	sed -i 's/^ENABLED=1$/ENABLED=0/' $CONF
	sync
	echo "MultiBootStartupMenu: boot menu disabled, the receiver will start slot $N directly."
else
	echo "MultiBootStartupMenu: boot menu still active (current slot not found): disable it from another slot or restore /boot/STARTUP."
fi
exit 0
"""


def add(tar, name, data, mode):
	info = tarfile.TarInfo(name)
	info.size = len(data)
	info.mode = mode
	info.uid = info.gid = 0
	info.uname = info.gname = "root"
	info.mtime = MTIME
	tar.addfile(info, io.BytesIO(data))


def add_dir(tar, name):
	info = tarfile.TarInfo(name)
	info.type = tarfile.DIRTYPE
	info.mode = 0o755
	info.uid = info.gid = 0
	info.uname = info.gname = "root"
	info.mtime = MTIME
	tar.addfile(info)


def targz(builder):
	buf = io.BytesIO()
	with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
		builder(tar)
	return buf.getvalue()


def data_tar(tar):
	parts = TARGET.split("/")
	add_dir(tar, "./")
	for i in range(1, len(parts) + 1):
		add_dir(tar, "./" + "/".join(parts[:i]) + "/")
	files = []
	for root, dirs, names in os.walk(SRC):
		dirs[:] = sorted(d for d in dirs if d != "__pycache__")
		rel = os.path.relpath(root, SRC)
		if rel != ".":
			add_dir(tar, "./%s/%s/" % (TARGET, rel))
		for name in sorted(names):
			if name.endswith((".pyc", ".tmp")):
				continue
			path = os.path.join(root, name)
			relname = os.path.normpath(os.path.join(rel, name))
			files.append(relname)
			with open(path, "rb") as f:
				data = f.read()
			add(tar, "./%s/%s" % (TARGET, relname), data, 0o755 if relname in EXEC else 0o644)
	return files


def control_tar(tar):
	add_dir(tar, "./")
	add(tar, "./control", CONTROL.encode(), 0o644)
	add(tar, "./postinst", POSTINST.encode(), 0o755)
	add(tar, "./prerm", PRERM.encode(), 0o755)


def ar_member(name, data):
	header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, MTIME, 0, 0, "100644", len(data))
	assert len(header) == 60
	out = header.encode() + data
	if len(data) % 2:
		out += b"\n"
	return out


def main(outdir):
	import i18n  # compile the catalogues first, so the package never ships a stale one
	i18n.main()
	listing = []
	data = targz(lambda tar: listing.extend(data_tar(tar)))
	control = targz(control_tar)
	ipk = b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") + ar_member("control.tar.gz", control) + ar_member("data.tar.gz", data)
	os.makedirs(outdir, exist_ok=True)
	path = os.path.join(outdir, "%s_%s_all.ipk" % (PACKAGE, VERSION))
	with open(path, "wb") as f:
		f.write(ipk)
	print(path)
	print("\n".join("  " + x for x in listing))
	return path


if __name__ == "__main__":
	main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT, "dist"))
