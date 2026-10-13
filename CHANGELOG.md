# Changelog

All the versions before 0.4.0 were called KexecBootMenu and were not published.

Version numbers: the third digit for fixes that change nothing the user sees
or has to know, the second one as soon as a behaviour changes or something is
added - a setting, a key, a receiver. The first stays at 0 until the whole
thing is worth calling finished. A number never means two different things:
any change to what goes into the package raises it, however small, and the
build refuses to overwrite a package of the same version built from different
sources.

## 0.7.1

The same report as a file, `/tmp/receiver-model.txt`, for whoever would
rather copy a file than photograph a screen. `/tmp` because it is the one
directory everybody who has ever copied an .ipk to a receiver already knows
how to reach. The one line comes first, the detail after it.

It is written at every start of the GUI, not only when the plugin is opened:
`/tmp` is emptied at every boot, and after the reboot of a trial the file has
to be there with the result of that trial in it. The screen now names the
file beside the line.

## 0.7.0

For people who install a plugin and never open a terminal, which is most
people. Everything a report needs is now on one line on the screen, so that a
photograph of it is a complete report:

    MBSM 0.7.0 | vuduo4kse | OpenBH 6.0.003 | boot OK | untested | trial ran

It carries the model string, which is the one thing that cannot be guessed
from what the screen otherwise shows: the receiver is called "Vu+ Duo4K SE"
there and `vuduo4kse` in the code, and it is the second one that has to go in
`SUPPORTED_MODELS`. The line appears in the setup screen and again in the
message that reports the result of a trial, with one sentence asking for the
photograph. It is left untranslated on purpose: it is meant to be read back,
not read.

## 0.6.1

Two fixes to 0.6.0, both found before anyone had run it.

**The trial is refused where the menu already starts at every boot.** A trial
ends by setting `ENABLED` back to 0. With `/boot/STARTUP` already pointing at
the menu, the wrapper would then refuse to run and hand over to the original
2nd stage, which boots what the menu line names - `rootsubdir=linuxrootfs0`,
the Recovery - at every start until someone fixed `/boot/STARTUP` by hand.
There was nothing to find out in that state anyway: a menu that starts at
every boot has already answered the question.

**The reason is written in the log again on a receiver where the plugin does
not appear.** 0.6.0 moved the decision into `Plugins()` and returned an empty
list, which also stopped the session-start hook from ever being registered -
and that hook was what wrote the line. On the one receiver where that line is
the only thing there is to report, nothing was written at all. It is now
written where the decision is taken.

## 0.6.0

A test version, meant to be tried on receivers nobody has tried it on yet.

Up to 0.5.0 the list of tested models decided whether the plugin existed at
all: on anything else it did not appear, so nobody outside those three
receivers could even find out whether it works. Now what decides is the
layout of the boot partition - STARTUP, STARTUP_RECOVERY, STARTUP.cpio.gz
and zImage, which is what the menu actually depends on. Where that layout is
there, the plugin appears, says plainly that this receiver has not been
tested, and does nothing at all until the user says yes to an entry that is
set to no. Where it is not there, the plugin stays away as before. The
tested list is now only what the warning hangs on.

**Try once (YELLOW).** The new way to find out, and the one to use first:
it writes the menu to `STARTUP_ONCE` instead of `STARTUP`, so the menu is
loaded at the next start and at that one only. `/boot/STARTUP` is not
touched. If the menu appears, it starts the chosen image and the receiver
goes back to exactly what it did before; if it does not appear, the receiver
starts as usual. Either way the plugin reports at the next start what the
trial proved - that the menu ran, that it was loaded but could not reach the
menu, or that the receiver ignored it altogether - which is the one fact a
new model has to establish.

The check for the Vu+ drivers in the Recovery is now a warning instead of a
refusal on receivers outside the tested list: another brand brings its
framebuffer up its own way. If it does not come up, the menu stage gives up
by itself and the fail-safe starts an image, as it always did.

A trial is refused where the menu already starts at every boot: there would
be nothing to find out, and ending it would set `ENABLED` back to 0 while
`/boot/STARTUP` still pointed at the menu, which boots the Recovery.

**`mbsm-report`**, a new command installed with the package: it only reads,
and prints everything about the receiver that a report has to contain -
model, image, what is in the boot partition, what the menu needs and whether
it is there. It can be run before installing anything.

## 0.5.0

Also runs on the Vu+ Solo 4K and Duo 4K SE, reported working by a forum
tester. Nothing else changed: no part of the plugin depends on the receiver
model - not the partition numbers, not the paths - so the whole change is the
list of models it is willing to run on.

When the plugin stays out of the way, it now writes one line in the debug log
saying which model string it saw and which of the three conditions failed, so
that a report from an untested receiver can be acted on.

## 0.4.0

Renamed. The plugin, the package and the translation domain are now
MultiBootStartupMenu / enigma2-plugin-systemplugins-multibootstartupmenu,
and the package declares Conflicts/Replaces/Provides on the old
enigma2-plugin-systemplugins-kexecbootmenu, so the two cannot end up
installed side by side. What lives in the boot partition keeps its old
names (/boot/bootmenu, bootmenu.cpio.gz): renaming those would orphan an
installation that is already running, for no gain.

The Recovery is the first entry of the menu and the fall-back of the
countdown. If the chosen image cannot be started when the countdown
expires, the Recovery starts - not the next slot in the list, which with
the same skin could be taken for the image that was asked for. The other
slots are tried only if the Recovery itself cannot start. The Recovery is
written to menu.txt (RECOVERY=) whether or not it is shown in the list, so
hiding it stays a matter of taste and does not remove the safety net.

## 0.3.3

The preview is on the BLUE button only. The Italian name of the menu entry
is shorter, so that it fits in skins with a narrow menu.

## 0.3.2

1. The preview is reachable. The log of the box shows that the key meant for
   it arrives as KEY_BLUE (401) and that nothing in the setup screen was
   bound to it: the yellow_button argument of Setup is not honoured by every
   image, and on some remotes the yellow key is not the one enigma2 calls
   yellow. The preview is now bound by the plugin itself to yellow *and*
   blue, and both buttons are labelled.
2. The Italian name of the menu entry (and of the screen) is now
   "Configurazione menu di avvio del Multiboot".
3. The Recovery can be chosen as the default image, not only shown in the
   menu: the choices of "Default image" follow "Show the Recovery in the
   menu" and are rebuilt when it changes. The help text of that setting now
   names the Recovery that was found, or says that none was found, so the
   screen itself shows what the plugin sees in the boot partition.

## 0.3.1

The preview really shows the picture. It was put on screen with ePicLoad
only, and its setPara() ignores anything that is not a *list* (enigma2 does
PyList_Check), which left the decoder with a size of 0x0 and the screen
black. The picture now goes through LoadPixmap, which is synchronous and is
what every plugin uses for a PNG; ePicLoad stays as a fallback, with a list
and with the framebuffer scale. The picture is rendered at the size of the
OSD, so nothing has to scale it, and if it still cannot be shown the screen
closes with the reason instead of staying black. Every step is logged with
the [MultiBootStartupMenu] prefix.

## 0.3.0

1. GREEN saves and the message appears at once, in the middle of the screen,
   and leaving the plugin closes it. RED leaves after one confirmation and
   shows nothing else; after a save it no longer claims there is something
   unsaved.
   In 0.2.0 those messages went through Tools.Notifications, which only the
   InfoBar serves: they appeared after leaving every menu. They are opened
   directly again, but now with the check enigma2 itself makes:

       if self.dialog_stack and not self.in_exec:
           raise RuntimeError("Modal open are allowed only from a screen
                               which is modal!")

   in_exec is True during a key handler or a timer callback, but
   Session.close() sets it to False and only the deferred pop of the closed
   dialog (delay_timer -> popCurrent -> execBegin) sets it back. That window
   is what crashed 0.1.0: it closed its wait box and opened the next dialog
   in the same callback. openLater() now tests the same condition and, if
   the session is in that window, tries again 50 ms later.
2. The preview works: same reason, it was queued instead of being shown.
3. The Recovery is in the menu again. It was looked up in
   SystemInfo["canMultiBoot"], which only lists linuxrootfs<n>
   subdirectories - and linuxrootfs0 does not exist, because the Recovery
   rootfs IS the root of the boot partition. It is now found by
   STARTUP_RECOVERY plus an image at the root of the partition, which is
   what the kexec stage actually boots.
4. The countdown is on the title line, in a large amber badge that turns
   red-orange for the last 3 seconds, instead of a thin line in the footer.
   It is its own frame area (count_<n>.bmf / count_off.bmf), so the footer
   keeps showing the key hints the whole time. The receiver model moved to
   the line above, next to VU+ MULTIBOOT.
Also: a wait box that ignores every key (a MessageBox could be dismissed
while the rendering thread was still running) and a 3-minute watchdog, so a
job that never answers cannot leave it on screen.

## 0.2.0

First fix of the crash of 0.1.0 (see above), by queueing the dialogs through
Tools.Notifications. Confirmed gone on OpenBH 5.6 and 6.0.003, independent
of the skin, but the messages arrived too late - 0.3.0 replaces it.
