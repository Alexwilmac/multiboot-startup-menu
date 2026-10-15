# -*- coding: utf-8 -*-
# MultiBootStartupMenu - renders the front display frames (in the running slot)
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# The front panel of a receiver like the Vu+ Ultimo 4K is a small colour
# screen - 800x480 at 32 bits on that one - and during the boot menu nothing
# else is using it: the image's splash has gone and enigma2 has not started.
# That makes it the one place the menu is readable when the television is off,
# on the wrong input, or still negotiating the HDMI link.
#
# The frames are prepared here, like the television ones, in the same BMF
# format: b"BMF1" + x, y, w, h (uint16 LE) + zlib(BGRA pixels).
#
#   lcd_item_<i>.bmf   the whole panel, entry i selected
#   lcd_boot_<i>.bmf   the whole panel, "starting entry i"
#   lcd_count_<n>.bmf  just the countdown pill, n seconds left
#   lcd_count_off.bmf  the same area, cleared
#
# This is not the television layout made smaller. The panel is a hand's width
# across and read from across the room, so it carries less: the entries, which
# one is chosen, and how long is left.

import os

from .render import (ACCENT, ACCENT_LIGHT, BADGE, BADGE_TEXT, BG_BOTTOM, BG_TOP,
	COUNT_BG, COUNT_BG_LAST, COUNT_EDGE, COUNT_EDGE_LAST, COUNT_FG, COUNT_FG_LAST,
	COUNT_LAST, DIVIDER, HL_TEXT, MUTED, ROW, ROW_TEXT, SCRATCH, Fonts, fit,
	text_width, write_bmf)
from PIL import Image, ImageDraw

# What a front panel has to be before the menu will draw on it. Anything
# smaller is a text display of a few characters, which this cannot use, and
# anything that is not 32 bits a colour this cannot write.
MIN_SIZE = (160, 96)
MAX_SIZE = (1920, 1080)


def usable(size, bpp=32):
	if bpp != 32 or not size:
		return False
	w, h = size
	return MIN_SIZE[0] <= w <= MAX_SIZE[0] and MIN_SIZE[1] <= h <= MAX_SIZE[1]


class LcdRenderer:
	"""entries: the same dicts the television menu is given.
	strings: the same localized texts; only a few of them are used here."""

	def __init__(self, entries, strings, size=(800, 480), fonts=None):
		self.w, self.h = int(size[0]), int(size[1])
		self.entries = entries
		self.s = strings
		self.fonts = fonts or Fonts()
		# Everything is a fraction of the panel, so a receiver with a display
		# of another size gets the same layout rather than a cropped one.
		self.margin = max(8, int(round(self.h * 0.058)))        # clear of the bezel
		self.head_h = max(18, int(round(self.h * 0.135)))
		self.list_top = self.margin + self.head_h + max(6, self.h // 60)
		self.list_bottom = self.h - self.margin
		n = max(1, len(entries))
		self.gap = max(3, int(round(self.h * 0.016)))
		avail = self.list_bottom - self.list_top
		self.row_h = max(14, min(int(round(self.h * 0.19)), (avail - self.gap * (n - 1)) // n))
		used = n * self.row_h + (n - 1) * self.gap
		self.top = self.list_top + max(0, (avail - used) // 2)
		self.count_box = self._count_box()   # the heading needs it: it sits beside it
		self.base = self._background()

	# ------------------------------------------------------------------
	def font(self, bold, fraction):
		return self.fonts.get(bold, max(8, int(round(self.h * fraction))))

	def _background(self):
		column = Image.new("RGBA", (1, self.h))
		for y in range(self.h):
			t = y / max(1, self.h - 1)
			column.putpixel((0, y), tuple(
				int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,))
		img = column.resize((self.w, self.h), Image.NEAREST)
		d = ImageDraw.Draw(img)
		f = self.font(True, 0.085)
		room = self.count_box[0] - self.margin - max(6, self.w // 80)
		brand = fit(SCRATCH, self.s.get("brand", "MultiBoot"), f, room)
		d.text((self.margin, self.margin), brand, font=f, fill=ACCENT_LIGHT)
		y = self.margin + self.head_h - max(2, self.h // 240)
		d.line([(self.margin, y), (self.w - self.margin, y)], fill=DIVIDER,
			width=max(1, self.h // 240))
		return img

	def _count_box(self):
		"""The countdown pill, at the right of the heading. Wide enough for the
		longest number it will ever show, so the area never has to change."""
		f = self.font(True, 0.105)
		unit = self.s.get("count_unit", "")
		width = text_width(SCRATCH, "88", f) + max(10, self.w // 60)
		if unit:
			width += text_width(SCRATCH, unit, self.font(False, 0.06)) + max(4, self.w // 150)
		height = max(14, int(round(self.h * 0.115)))
		x = self.w - self.margin - width
		y = self.margin + max(0, (self.head_h - height) // 2) - max(1, self.h // 160)
		return (x, y, width, height)

	# ------------------------------------------------------------------
	def count_frame(self, seconds):
		x, y, w, h = self.count_box
		img = self.base.crop((x, y, x + w, y + h)).copy()
		if seconds is None:
			return img
		last = seconds <= COUNT_LAST
		bg = COUNT_BG_LAST if last else COUNT_BG
		edge = COUNT_EDGE_LAST if last else COUNT_EDGE
		fg = COUNT_FG_LAST if last else COUNT_FG
		d = ImageDraw.Draw(img)
		r = h // 2
		d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=bg, outline=edge,
			width=max(1, self.h // 240))
		f = self.font(True, 0.105)
		text = str(seconds)
		tw = text_width(SCRATCH, text, f)
		unit = self.s.get("count_unit", "")
		fu = self.font(False, 0.06)
		uw = text_width(SCRATCH, unit, fu) if unit else 0
		pad = max(2, self.w // 200)
		start = (w - (tw + (uw + pad if unit else 0))) // 2
		box = d.textbbox((0, 0), text, font=f)
		d.text((start, (h - (box[3] - box[1])) // 2 - box[1]), text, font=f, fill=fg)
		if unit:
			ub = d.textbbox((0, 0), unit, font=fu)
			d.text((start + tw + pad, (h - (ub[3] - ub[1])) // 2 - ub[1] + max(1, self.h // 200)),
				unit, font=fu, fill=fg)
		return img

	# ------------------------------------------------------------------
	def _row(self, img, index, entry, selected):
		d = ImageDraw.Draw(img)
		y = self.top + index * (self.row_h + self.gap)
		x0, x1 = self.margin, self.w - self.margin
		radius = max(3, self.row_h // 5)
		d.rounded_rectangle([x0, y, x1 - 1, y + self.row_h - 1], radius=radius,
			fill=ACCENT if selected else ROW)
		# the slot number, in a square badge: the one thing that must be read
		# from across the room
		bw = self.row_h - max(4, self.row_h // 6)
		bx = x0 + max(3, self.row_h // 8)
		by = y + (self.row_h - bw) // 2
		d.rounded_rectangle([bx, by, bx + bw - 1, by + bw - 1], radius=max(2, bw // 5),
			fill=HL_TEXT if selected else BADGE)
		fs = self.fonts.get(True, max(8, int(self.row_h * 0.52)))
		slot = str(entry["slot"])
		sb = d.textbbox((0, 0), slot, font=fs)
		d.text((bx + (bw - (sb[2] - sb[0])) // 2 - sb[0],
			by + (bw - (sb[3] - sb[1])) // 2 - sb[1]), slot, font=fs,
			fill=ACCENT if selected else BADGE_TEXT)
		# the name of the image, and its tag underneath when there is room
		tx = bx + bw + max(5, self.row_h // 5)
		room = x1 - tx - max(4, self.row_h // 6)
		tag = entry.get("tag") or ""
		two = self.row_h >= 34 and tag
		fn = self.fonts.get(True, max(8, int(self.row_h * (0.34 if two else 0.42))))
		name = fit(SCRATCH, entry.get("name") or entry.get("label") or "", fn, room)
		nb = d.textbbox((0, 0), name, font=fn)
		if two:
			ft = self.fonts.get(False, max(7, int(self.row_h * 0.25)))
			tag = fit(SCRATCH, tag, ft, room)
			tb = d.textbbox((0, 0), tag, font=ft)
			block = (nb[3] - nb[1]) + max(2, self.row_h // 14) + (tb[3] - tb[1])
			ny = y + (self.row_h - block) // 2
			d.text((tx, ny - nb[1]), name, font=fn, fill=HL_TEXT if selected else ROW_TEXT)
			d.text((tx, ny + (nb[3] - nb[1]) + max(2, self.row_h // 14) - tb[1]), tag,
				font=ft, fill=ACCENT_LIGHT if selected else MUTED)
		else:
			d.text((tx, y + (self.row_h - (nb[3] - nb[1])) // 2 - nb[1]), name, font=fn,
				fill=HL_TEXT if selected else ROW_TEXT)

	def item_frame(self, index):
		img = self.base.copy()
		for i, entry in enumerate(self.entries):
			self._row(img, i, entry, i == index)
		return img

	def boot_frame(self, index, label=None):
		"""The panel while a slot is being started: the list goes, the name
		stays, because by then it is the only thing worth reading."""
		img = self.base.copy()
		d = ImageDraw.Draw(img)
		if label is None:
			entry = self.entries[index]
			label = entry.get("name") or entry.get("label") or ""
		text = self.s.get("starting", "Starting %s") % label
		f = self.font(True, 0.115)
		area = self.w - 2 * self.margin
		text = fit(SCRATCH, text, f, area)
		box = d.textbbox((0, 0), text, font=f)
		d.text((self.margin + (area - (box[2] - box[0])) // 2 - box[0],
			self.list_top + (self.list_bottom - self.list_top - (box[3] - box[1])) // 2 - box[1]),
			text, font=f, fill=ROW_TEXT)
		return img

	# ------------------------------------------------------------------
	def write_all(self, folder, timeout, recovery=None):
		"""No size is passed to write_bmf: these frames are already drawn at
		the panel's own size, so there is nothing for it to fit them to."""
		os.makedirs(folder, exist_ok=True)
		for i in range(len(self.entries)):
			write_bmf(os.path.join(folder, "lcd_item_%d.bmf" % i), self.item_frame(i), 0, 0)
			write_bmf(os.path.join(folder, "lcd_boot_%d.bmf" % i), self.boot_frame(i), 0, 0)
		if recovery:
			write_bmf(os.path.join(folder, "lcd_boot_recovery.bmf"),
				self.boot_frame(0, recovery[1]), 0, 0)
		x, y = self.count_box[0], self.count_box[1]
		for n in range(int(timeout) + 1):
			write_bmf(os.path.join(folder, "lcd_count_%d.bmf" % n), self.count_frame(n), x, y)
		write_bmf(os.path.join(folder, "lcd_count_off.bmf"), self.count_frame(None), x, y)
