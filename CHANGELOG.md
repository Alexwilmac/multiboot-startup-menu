# Changelog

All the versions before 0.4.0 were called KexecBootMenu and were not published.

Version numbers: the third digit for fixes that change nothing the user sees
or has to know, the second one as soon as a behaviour changes or something is
added - a setting, a key, a receiver. The first stays at 0 until the whole
thing is worth calling finished. A number never means two different things:
any change to what goes into the package raises it, however small, and the
build refuses to overwrite a package of the same version built from different
sources.

## 0.8.2

**The front display is turned up to full.** 0.8.1 set the brightness to 10,
which is what the probe had used, without knowing where the scale ended: it
ends at 255, so 10 was close to the bottom and the panel was readable but
dim. `LCDBRIGHT` still overrides it.

## 0.8.1

**The menu appears on the front display as well.** A receiver like the Vu+
Ultimo 4K has a small colour screen on its front - 800x480 at 32 bits - and
during the boot menu nothing is using it: the image's splash has gone and
enigma2 has not started. That is the one place the menu can be read when the
television is off, on another input, or still settling the HDMI link, which
is exactly when being unable to choose a slot is most annoying.

The panel shows the entries, which one is chosen and the countdown, following
the keys like the television does. It is not the television layout made
smaller: the panel is read from across the room, so it carries the slot
number large, the image name beside it, and nothing else.

Three things had to be found out on the receiver itself, and all three are
now handled:

- the panel takes a whole frame at a time, so the tiles are composed in
  memory and handed over in one write;
- its colours are in the order blue, green, red - the same as the television
  frames, so the drawing needed no special case;
- **its backlight is off until enigma2 turns it on.** Without that the
  picture is there and nobody can see it. The menu now turns the brightness
  up itself (`/proc/stb/fp/oled_brightness` on this receiver), and switches
  off the live television overlay some of these panels can show.

Receivers differ, so nothing is assumed: the plugin reads the panel where
enigma2 reads it and draws only for a colour display big enough to be worth
it. A receiver with a few characters of text, or with no display at all, gets
the menu on the television exactly as before and never looks for the frames.
Nothing about the panel is allowed to stop the menu: a display that cannot be
opened, or a frame that cannot be read, costs the panel and nothing else.

`LCD=0` in bootmenu.conf leaves the front display alone, and `LCDBRIGHT` sets
how bright it is turned up.

The number skips 0.8.0: that one was built and installed once before being
renamed 0.7.5, so it already means something else on at least one receiver.

## 0.7.9

**Two ways of putting the menu on the screen without letting the scaler
stretch it.** The receiver's OSD rectangle turned out to be the ordinary
full-screen one (720x576 in the units the driver takes, which is what enigma2
writes too), so nothing was misconfigured. But that rectangle is also the
lever: it says where the framebuffer lands, and a framebuffer that lands at
its own size is not scaled at all.

`OSDMODE` in bootmenu.conf, empty by default, which is what every version so
far did:

- **native** - the framebuffer goes on the screen pixel for pixel, centred.
  On a Vu+ 4K that is a 1920x1440 area in the middle of a 3840x2160 screen,
  so the menu is a quarter of the screen's area and perfectly sharp: nothing
  resamples it.
- **double** - the framebuffer goes on at exactly twice its size, anchored at
  the top left. Its lower part falls off the bottom of the screen, which is
  the point: the menu is drawn in the top 1080 rows and those cover the whole
  screen at exactly 2:1 - the same clean doubling the enigma2 GUI gets, and
  full screen with it.

With either mode the frames go back to the plain 1920x1080 design: the
horizontal squeeze of 0.7.6 existed only to cancel a stretch that no longer
happens. The frames carry the mode in their signature, so changing it rebuilds
them.

The rectangle is worked out from the framebuffer and the output resolution the
receiver is actually driving, not from constants, and if the output resolution
cannot be read the rectangle is left exactly as it was.

## 0.7.8

**A test pattern on the boot screen, to find out what the receiver does to
the picture.** Measurements have now closed every explanation but one. The
output is 2160p50 during the menu, the same as under enigma2; the framebuffer
is 1920 wide at 32 bits in both cases; what differs is the height - enigma2
gets 1080 rows, the menu stage gets 1440 - and the framebuffer memory,
22118400 bytes, is exactly two buffers of 1440 rows, so a 4K surface was
never going to fit. The whole difference from the GUI is therefore one thing:
the hardware turns every 2 rows into 3 instead of doubling them.

Whether anything can be done about that depends on *how* it turns 2 into 3,
and nothing can be read back from the screen to find out. So the menu can now
draw a pattern of 1-, 2- and 3-row lines, written straight into the
framebuffer, which tells the two cases apart at a glance: if rows are
repeated, lines 2 rows thick come out perfectly even and the menu can be
drawn on a grid that survives the scale; if rows are mixed, everything turns
grey and no amount of drawing will help.

YELLOW or BLUE on the boot screen shows it. It is not part of the menu,
nothing announces it, and it is left undocumented.

Also: the OSD rectangle (`/proc/stb/fb/dst_*`) is written to the log at menu
time. enigma2 sets it when it starts, nothing sets it here, and its value in
this phase had never been seen.

Nothing a user sees has changed.

## 0.7.7

**An update can no longer break the version it is replacing.** Installing
0.7.6 over 0.7.5 and pressing GREEN without restarting ended in a Python
message about `write_all()` and the wrong number of arguments. The package
was correct; the two halves running were not. enigma2 keeps the modules it
loaded when it started, and the drawing code is read from disk only when the
frames are actually drawn - so for the rest of that session the caller is the
old version and the drawing code the new one. 0.7.6 had moved an argument
between the two, and they stopped understanding each other.

Two changes, so that this cannot bite again:

- the drawing code accepts the call as it was *and* as it is now, and both
  produce the same frames - checked, not assumed;
- if any such mismatch ever appears, the plugin says what to do - restart the
  user interface - instead of showing a Python message nobody can act on.

The test suite now calls the plugin's own drawing entry point, the way GREEN
calls it, rather than building the renderer by hand. That was the real gap:
the two halves were never put together off the box, so only the receiver
could notice they disagreed. It also runs the previous version's call, which
reproduces the failure exactly when the compatibility is removed.

Nothing changed in what the menu looks like or does: frames built by 0.7.6
and by 0.7.7 are identical.

## 0.7.6

**The menu is drawn at the density of the framebuffer, not stretched to it.**
0.7.5 put the frames at the right size but got there by drawing the layout at
1080 rows and resampling: the geometry came out right - a square badge
measured square on the screen - and the softness stayed, because resampling
cannot invent the rows it adds. The layout is now written in numbers that are
multiplied by a scale, so a 1920x1440 framebuffer is drawn on a 2560x1440
canvas and only then squeezed to 1920 wide: the glyphs are rasterised with
1440 rows of real detail, and the only resampling left is a horizontal
reduction, which costs nothing. At the usual 1920x1080 the scale is 1 and the
frames come out identical to 0.7.5's, pixel for pixel - which is how the
change was checked.

**The reset after a choice no longer goes through an ordinary reboot.** Twice
in a row the receiver stayed dark after the menu had done everything right:
the log ended at `reboot (slot 1)` and nothing followed. A reboot asks every
driver to shut down first, and by then the whole Vu+ platform is up - tuners,
CI, card readers, front panel, FPGA - none of which the menu needed; one of
them hanging in its shutdown hook leaves the box dark. The menu stage now
flushes the filesystems, remounts them read-only and resets through sysrq,
which does not ask the drivers anything. The old path is still there for a
kernel without sysrq.

## 0.7.5

**The menu is drawn for the framebuffer the receiver actually has.**

Measured on a Vu+ Ultimo 4K: the same word was 22% taller, relative to its
width, in the menu at boot than in the preview inside the plugin, and soft
with it. The log had been saying why all along. The Recovery of that receiver
brings the framebuffer up at `1920x1440`, and those 1440 rows cover the whole
screen - so its pixels are a third wider than they are tall. Asking for
`1920x1080` was accepted and read back as `1920x1080`, and the picture stayed
stretched: the mode change does not reach what feeds the screen. Writing 1080
rows into it without asking, which this release can be told to do, leaves the
picture squashed instead - the proof that those 1440 rows are the screen.

So the frames are now drawn at that size. The menu stage records what the
driver gave it in `bootmenu.conf` as `FBNATIVE`, the plugin draws the frames
for it, and the menu stage then leaves the framebuffer alone, because what is
there is already what it wants. Nothing is rescaled anywhere: not by us, not
by the hardware. Where the framebuffer is 1920x1080 to begin with, nothing
changes at all.

It takes two restarts to settle on a receiver the menu has never run on,
because the size cannot be known before the menu has run once. `FBMODE=force`
in `bootmenu.conf` goes back to asking for the frames' size, the way every
version up to 0.7.2 did.

**The report line names the code in the boot partition** when it is not the
same as the plugin's. The two are updated at different moments - the plugin
when the package is installed, the boot partition a minute after the
interface starts - and a report that named only one of them could describe a
version that was not the one running.

## 0.7.2

**The menu is sharp on the television again.** menu-init writes the OSD
rectangle while the framebuffer is still the one the Recovery's driver set up
— 1920x1440 on a Vu+ 4K — and the scaler is latched against that source size.
A quarter of a second later the menu stage changes the mode to 1920x1080, and
nothing told the scaler: it went on stretching 1080 lines as if they were
1440, on top of the upscale to the television's own resolution. That is why
the preview inside the plugin was perfect and the menu on screen was not. The
values are now written again from the menu stage, once the framebuffer is
what it will stay.

The confirmation shown before a trial no longer promises that the receiver
"starts as usual" if the menu is not loaded: the menu line is built on the
Recovery line, so on a receiver that ignores it the Recovery is what starts.
Nothing is changed either way, and one more restart goes back to the usual
image — which is what it says now.

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
