# Builds a fake mmcblk0p4 (Recovery root + kexec slots) like the one of a Vu+ Ultimo4K
import gzip
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.abspath(os.path.join(HERE, "..", ".."))
ORIG_INITRD = os.path.join(SCRATCH, "kxm", "vuultimo4k", "STARTUP_cpio.bin")

STAGE2_INIT = b"""#!/bin/sh
# stand-in for the Vu+ 2nd stage initrd
mount -t proc proc /proc
exec switch_root /newroot /sbin/init
"""


def synthetic_initrd():
	"""A minimal STARTUP.cpio.gz when the real one is not next to the tests.
	It only has to satisfy the checks of core.build_initrd: a single /init
	that calls switch_root, and a busybox."""
	sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
	from MultiBootStartupMenu.core import cpio_build
	entries = [
		{"name": "./init", "data": STAGE2_INIT, "ino": 1, "mode": 0o100755, "nlink": 1},
		{"name": "./bin", "data": b"", "ino": 2, "mode": 0o040755, "nlink": 2},
		{"name": "./bin/busybox.nosuid", "data": b"\x7fELF-busybox", "ino": 3, "mode": 0o100755, "nlink": 1},
	]
	return gzip.compress(cpio_build(entries), compresslevel=6, mtime=0)

STARTUPS = {
	"STARTUP": "kernel=/linuxrootfs3/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs3",
	"STARTUP_1": "kernel=/linuxrootfs1/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs1",
	"STARTUP_2": "kernel=/linuxrootfs2/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs2",
	"STARTUP_3": "kernel=/linuxrootfs3/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs3",
	"STARTUP_RECOVERY": "kernel=/zImage root=/dev/mmcblk0p4 rootsubdir=linuxrootfs0",
}


def write(path, data, mode=0o644):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb" if isinstance(data, bytes) else "w") as f:
		f.write(data)
	os.chmod(path, mode)


def build(root, slots=(1, 2, 3)):
	shutil.rmtree(root, ignore_errors=True)
	os.makedirs(root)
	for name, text in STARTUPS.items():
		write(os.path.join(root, name), text)
	if os.path.isfile(ORIG_INITRD):
		shutil.copyfile(ORIG_INITRD, os.path.join(root, "STARTUP.cpio.gz"))
	else:
		write(os.path.join(root, "STARTUP.cpio.gz"), synthetic_initrd())
	write(os.path.join(root, "zImage"), b"RECOVERY-KERNEL")
	write(os.path.join(root, "bin", "busybox.nosuid"), b"ELF", 0o755)
	os.symlink("/bin/busybox.nosuid", os.path.join(root, "bin", "sh"))
	write(os.path.join(root, "usr", "bin", "python3.13"), b"ELF", 0o755)
	os.symlink("python3.13", os.path.join(root, "usr", "bin", "python3"))
	write(os.path.join(root, "usr", "bin", "enigma2"), b"ELF", 0o755)
	write(os.path.join(root, "usr", "lib", "enigma.info"), "distro=openbh\n")
	write(os.path.join(root, "etc", "init.d", "vuplus-platform-util"), "#!/bin/sh\n", 0o755)
	write(os.path.join(root, "lib", "modules", "3.14.28-1.12", "extra", "brcmfb.ko"), b"KO")
	for n in slots:
		write(os.path.join(root, "linuxrootfs%d" % n, "zImage"), b"SLOT-KERNEL")
		write(os.path.join(root, "linuxrootfs%d" % n, "usr", "bin", "enigma2"), b"ELF", 0o755)
	for d in ("run", "dev/input", "proc/stb/video", "proc/stb/fb", "proc/stb/fp"):
		os.makedirs(os.path.join(root, d), exist_ok=True)
	for name in ("video/videomode", "video/alpha", "fb/dst_left", "fb/dst_width", "fb/dst_top", "fb/dst_height", "fp/remote_code"):
		write(os.path.join(root, "proc", "stb", name), "")
	return root
