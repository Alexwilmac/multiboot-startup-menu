# How it works

## Boot flow

```
BOLT
 └─ kexec 1st stage (kernel_auto.bin) reads /STARTUP, which the plugin has set to
    <the STARTUP_RECOVERY line> initrd=bootmenu/bootmenu.cpio.gz
     └─ Recovery kernel (/zImage) + bootmenu.cpio.gz
        bootmenu.cpio.gz is the receiver's own STARTUP.cpio.gz with one file added:
        the original /init is kept as /init.stage2 and a new /init wraps it
         └─ /init (payload/init)
            menu installed and enabled?  yes → switch_root into the Recovery rootfs
                                               running /bootmenu/menu-init
                                          no → exec /init.stage2, i.e. the normal boot
             └─ menu-init (PID 1)
                loads the Recovery's Vu+ drivers (vuplus-platform-util), restores the
                video mode, OSD geometry and remote-control code the plugin saved,
                then runs runner.py
                 └─ runner.py (the Recovery's python3, standard library only)
                    draws the pre-rendered frames straight on /dev/fb0 (mmap +
                    FBIO_BLIT, the way enigma2 does) and reads the remote control
                    from /dev/input/event*
                     └─ writes the choice to /STARTUP_ONCE and calls reboot -f
                         └─ kexec 1st stage starts STARTUP_ONCE; the original 2nd
                            stage of that slot deletes it, so it is a one-time boot
                            and /STARTUP still points at the menu
```

The extra reboot is needed because each slot may have its own kernel, and the
1st stage is the only thing that can load it.

## What is written, and where

Everything lives in the boot partition (`mmcblk0p4`), which every slot sees as
`/boot`. Nothing is written inside any image.

| Path | Written by | What it is |
| --- | --- | --- |
| `/boot/STARTUP` | plugin | the Recovery line plus `initrd=bootmenu/bootmenu.cpio.gz`. The previous content is kept in `bootmenu/STARTUP.before` |
| `/boot/bootmenu/bootmenu.cpio.gz` | plugin | the menu initrd, built on the receiver from its own `STARTUP.cpio.gz` and verified entry by entry |
| `/boot/bootmenu/menu-init`, `runner.py` | plugin | the menu stage |
| `/boot/bootmenu/frames/` | plugin | the pre-rendered screens, about 0.5–1.5 MB |
| `/boot/bootmenu/bootmenu.conf` | plugin and menu | the settings, shared by every slot; the menu updates `LAST` |
| `/boot/STARTUP_ONCE` | menu, image selector | the slot to start once; the original 2nd stage deletes it |
| `/boot/bootmenu/bootmenu.log`, `.log.1`, `dmesg.txt`, `status` | menu | what the last two runs of the menu did |

The names under `/boot/bootmenu` are the ones the plugin used when it was
called KexecBootMenu. They were deliberately left alone: renaming them would
orphan an installation that is already running.

## The frames

The menu stage has no fonts and no PIL, so every state of the screen is
rendered in advance by the plugin, in the running slot. A `.bmf` file is
`b"BMF1"` + `x, y, w, h` (uint16 LE) + zlib-compressed BGRA pixels, which is
what the framebuffer wants, so the menu stage only has to decompress and copy.

| File | Area |
| --- | --- |
| `item_<i>.bmf` | the whole screen, entry *i* highlighted |
| `count_<n>.bmf` | the countdown badge on the title line, *n* seconds left |
| `count_off.bmf` | the same area, empty: clears the badge at the first key press |
| `idle.bmf` | the footer with the key hints — the normal footer |
| `boot_<i>.bmf` | the footer, "starting …" |
| `boot_recovery.bmf` | the same, for the Recovery when it is not in the list |
| `error.bmf` | the footer, "this image cannot be started" |
| `menu.txt` | the entries, the countdown length, the fall-back Recovery, a signature |

The signature covers the entries, the texts, the model and the plugin version.
A minute after every start, a slot with the plugin compares it with what the
images in the slots are now, and re-renders only if something changed.

## Is an image startable?

When the countdown expires, the menu stage checks — on the partition it
already has mounted — that the `STARTUP_n` file exists and names a `kernel=`
and a `root=`, that the kernel file is there, and that the rootfs
subdirectory holds `usr/bin/enigma2` (for the Recovery, whose rootfs is the
root of the partition, `sbin/init` is enough).

It is a check for the things that are *missing* after an image has been
deleted or a restore left a slot incomplete, not a promise that the boot will
succeed. Two things it cannot see:

- slots on another device (USB): the menu stage does not mount it, so those
  are left to the kexec 1st stage;
- an image that is there but then fails to start. The menu has handed over
  control by then — the same as a MultiBoot without the menu. Switching the
  receiver off and on brings the menu back, because `/STARTUP` was never
  touched and the slot's own 2nd stage has already deleted `/STARTUP_ONCE`.

## Safety

- `.running` is written before the menu draws anything and removed once it
  has. Finding it still there means the previous run failed: the default slot
  is started once (`FAILSAFE`). Twice in a row and `/boot/STARTUP` is put back
  on the default slot and the menu turns itself off (`DISABLED`).
- A 60-second watchdog and `panic=10` in the menu stage: a stuck menu reboots
  instead of leaving a dead receiver.
- `.wrapper_pending`: if the hand-over to the menu stage failed, the next boot
  goes to the original 2nd stage.
- `.unverified` is set whenever `/boot/STARTUP` is pointed at the menu and
  removed by the initrd wrapper the first time it actually runs. If the plugin
  finds `/boot/STARTUP` changed while the marker is still there, the menu never
  ran even once: it is disabled rather than put back.
- The menu stage never changes `/boot/STARTUP`, except for the two-failure
  fail-safe above.

## The plugin side

| File | |
| --- | --- |
| `core.py` | everything that touches the boot partition: the cpio builder, the configuration, the `STARTUP` files. No enigma2 imports, so it can be tested off the receiver |
| `render.py` | the frames, with PIL |
| `glue.py` | the enigma2 side: repair at session start, and the patches that make `MultiBootSelector.reboot`, `OpenBhImageManager.FlashQuestion` and `Tools.Multiboot.activateSlot` write `STARTUP_ONCE` instead of `STARTUP` while the menu is enabled |
| `ui.py` | the setup, wait and preview screens |
| `payload/` | `init` (the initrd wrapper), `menu-init`, `runner.py` — the three files that run before any image |

### Dialogs and the exec context

enigma2 refuses to open a modal dialog while the session is not "in exec":

```python
def open(self, screen, *arguments, **kwargs):
    if self.dialog_stack and not self.in_exec:
        raise RuntimeError("[StartEnigma] Error: Modal open are allowed only from a screen which is modal!")
```

`in_exec` is true inside a key handler or a timer callback, but
`Session.close()` sets it to false and only the deferred pop of the closed
dialog (`delay_timer` → `popCurrent` → `execBegin`) sets it back. Closing a
dialog and opening the next one in the same callback lands in that window and
raises. `ui.openLater()` tests the same condition and, if the session is in
that window, tries again a few milliseconds later.
