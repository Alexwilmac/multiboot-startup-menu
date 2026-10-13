#!/bin/sh
# MultiBootStartupMenu - what this receiver looks like
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# Run it over SSH and send back everything it prints. It only reads: no file
# of the receiver is written or changed, and it is safe to run at any time,
# with or without the plugin installed.
#
#     sh mbsm-report.sh
#
# Installed with the package, it is simply:  mbsm-report

# MBSM_BOOT is only used by the test suite
BOOT=${MBSM_BOOT:-/boot}

say() {
	echo "$*"
}

head_() {
	echo
	echo "--- $1 ---"
}

read_() {
	if [ -r "$1" ]; then
		tr -d '\000' < "$1" | head -n "${2:-1}"
	else
		echo "(not readable)"
	fi
}

have() {
	# -L as well: inside the boot partition /bin/sh is a symlink whose target
	# is written as an absolute path, which only resolves once that partition
	# is the root - that is, while the menu is running
	if [ -e "$1" ] || [ -L "$1" ]; then echo yes; else echo no; fi
}

missing_if_absent() {
	[ -e "$1" ] || [ -L "$1" ] || MISSING="$MISSING $2"
}

say "=== MultiBootStartupMenu report ==="
say "date: $(date 2>/dev/null)"

head_ "receiver"
for f in vumodel boxtype model machinebuild brandoem; do
	[ -f /proc/stb/info/$f ] && say "/proc/stb/info/$f: $(read_ /proc/stb/info/$f)"
done
say "uname: $(uname -a 2>/dev/null)"

head_ "image"
if [ -f /etc/os-release ]; then
	grep -E '^(PRETTY_NAME|ID|VERSION_ID)=' /etc/os-release
elif [ -f /etc/image-version ]; then
	head -n 5 /etc/image-version
else
	say "(no /etc/os-release)"
fi
say "python3: $(python3 -V 2>&1)"
say "PIL: $(python3 -c 'import PIL; print(PIL.__version__)' 2>&1 | tail -n 1)"

head_ "multiboot"
say "/proc/cmdline: $(read_ /proc/cmdline)"
say "$BOOT mounted: $(grep -c " $BOOT " /proc/mounts 2>/dev/null)"
say "free in $BOOT: $(df -h $BOOT 2>/dev/null | awk 'NR==2 {print $4}')"
say ""
say "files in $BOOT:"
ls -la $BOOT 2>/dev/null | head -n 40

head_ "STARTUP files"
for f in $BOOT/STARTUP $BOOT/STARTUP_ONCE $BOOT/STARTUP_RECOVERY $BOOT/STARTUP_[0-9]*; do
	[ -f "$f" ] || continue
	say "$(basename "$f"): $(read_ "$f")"
done

head_ "what the menu needs"
say "STARTUP............: $(have $BOOT/STARTUP)"
say "STARTUP_RECOVERY...: $(have $BOOT/STARTUP_RECOVERY)"
say "STARTUP.cpio.gz....: $(have $BOOT/STARTUP.cpio.gz)  $(ls -l $BOOT/STARTUP.cpio.gz 2>/dev/null | awk '{print $5" bytes"}')"
say "zImage.............: $(have $BOOT/zImage)"
say "Recovery /bin/sh...: $(have $BOOT/bin/sh)"
say "Recovery python3...: $(have $BOOT/usr/bin/python3)"
say "Recovery drivers...: $(have $BOOT/etc/init.d/vuplus-platform-util) (vuplus-platform-util)"
say "  kernel modules...: $(ls -d $BOOT/lib/modules/*/extra 2>/dev/null | head -n 1)"
say "framebuffer /dev/fb0: $(have /dev/fb0)"

head_ "2nd stage (STARTUP.cpio.gz)"
if [ -f $BOOT/STARTUP.cpio.gz ]; then
	if command -v cpio > /dev/null 2>&1; then
		zcat $BOOT/STARTUP.cpio.gz 2>/dev/null | cpio -t 2>/dev/null | head -n 20
	else
		say "(no cpio here to list it: not a problem, the plugin reads it itself)"
	fi
	if zcat $BOOT/STARTUP.cpio.gz 2>/dev/null | grep -qa switch_root; then
		say "contains switch_root: yes"
	else
		say "contains switch_root: NO"
	fi
else
	say "(missing)"
fi

head_ "plugin"
if [ -d /usr/lib/enigma2/python/Plugins/SystemPlugins/MultiBootStartupMenu ]; then
	say "installed: yes"
	grep -m1 '^VERSION' /usr/lib/enigma2/python/Plugins/SystemPlugins/MultiBootStartupMenu/core.py 2>/dev/null
	[ -f $BOOT/bootmenu/bootmenu.conf ] && say "" && say "bootmenu.conf:" && cat $BOOT/bootmenu/bootmenu.conf
	[ -f $BOOT/bootmenu/status ] && say "status: $(cat $BOOT/bootmenu/status)"
	[ -f $BOOT/bootmenu/bootmenu.log ] && say "" && say "last menu run (bootmenu.log, last 30 lines):" && tail -n 30 $BOOT/bootmenu/bootmenu.log
else
	say "installed: no"
fi

head_ "verdict"
MISSING=""
for f in STARTUP STARTUP_RECOVERY STARTUP.cpio.gz zImage; do
	[ -f $BOOT/$f ] || MISSING="$MISSING $f"
done
for f in bin/sh usr/bin/python3; do
	missing_if_absent "$BOOT/$f" "Recovery:$f"
done
if [ -n "$MISSING" ]; then
	say "NOT compatible: missing in $BOOT:$MISSING"
	say "This receiver does not have the boot layout the menu works with."
else
	say "The boot layout is complete: the menu can be tried on this receiver."
	say "It is still a test: use YELLOW (Try once) in the plugin before switching it on for good."
fi
say ""
say "=== end of report ==="
