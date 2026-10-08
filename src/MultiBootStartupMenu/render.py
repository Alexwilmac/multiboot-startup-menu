# -*- coding: utf-8 -*-
# MultiBootStartupMenu - renders the boot menu frames with PIL (in the running slot)
# Copyright (C) 2026 AlexWilMac
# SPDX-License-Identifier: GPL-2.0-only
#
# The menu stage has no fonts or PIL, so every screen state is prepared here:
#   item_<i>.bmf   full screen, entry i highlighted (footer and countdown empty)
#   count_<n>.bmf  countdown badge next to the title, n seconds left
#   count_off.bmf  same area, empty: clears the badge when a key is pressed
#   boot_<i>.bmf   footer "starting ..." for entry i
#   idle.bmf       footer with the key hints (the normal footer)
#   error.bmf      footer "this image cannot be started"
#   menu.txt       entries, countdown length, signature
# A .bmf file is b"BMF1" + x, y, w, h (uint16 LE) + zlib(BGRA pixels).
#
# The countdown is deliberately NOT in the footer: it sits on the title line,
# in a large coloured badge, because a thin line at the bottom of a TV screen
# goes unnoticed.

import os
import zlib

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
X0, X1 = 160, 1760
BRAND_Y, TITLE_Y, DIVIDER_Y = 100, 160, 222
LIST_TOP, LIST_BOTTOM = 262, 900
FOOTER_Y, FOOTER_H = 930, 100
COUNT_Y, COUNT_H = 112, 96  # band around the title line, right side
COUNT_PILL_H = 76
TITLE_SIZES = (58, 52, 46, 40, 34, 30)

BG_TOP = (18, 27, 45)
BG_BOTTOM = (7, 11, 20)
ROW = (25, 36, 58)
ROW_TEXT = (222, 230, 242)
MUTED = (136, 154, 180)
ACCENT = (41, 108, 222)
ACCENT_LIGHT = (130, 176, 248)
HL_TEXT = (255, 255, 255)
HL_TAG = (212, 226, 250)
BADGE = (40, 55, 82)
BADGE_TEXT = (176, 194, 220)
ERROR = (244, 150, 80)
DIVIDER = (42, 57, 84)
# countdown badge: amber, red-orange for the last seconds
COUNT_BG = (255, 182, 38)
COUNT_EDGE = (255, 214, 130)
COUNT_FG = (38, 26, 2)
COUNT_CAP = (92, 62, 6)
COUNT_BG_LAST = (240, 72, 48)
COUNT_EDGE_LAST = (255, 158, 140)
COUNT_FG_LAST = (255, 255, 255)
COUNT_CAP_LAST = (255, 216, 208)
COUNT_LAST = 3  # seconds shown in the alarm colour

FONT_DIRS = ("/usr/share/fonts",)
REGULAR = ("OpenSans-Regular.ttf", "DroidSans.ttf", "nmsbd.ttf")
SEMIBOLD = ("OpenSans-Semibold.ttf", "OpenSans-Bold.ttf", "DroidSans-Bold.ttf", "nmsbd.ttf")


class Fonts:
	def __init__(self, dirs=None):
		self.dirs = dirs or FONT_DIRS
		self.cache = {}

	def _find(self, names):
		for folder in self.dirs:
			for name in names:
				path = os.path.join(folder, name)
				if os.path.isfile(path):
					return path
		for folder in self.dirs:
			try:
				for name in sorted(os.listdir(folder)):
					if name.lower().endswith(".ttf"):
						return os.path.join(folder, name)
			except OSError:
				pass
		return None

	def get(self, bold, size):
		key = (bold, size)
		if key not in self.cache:
			path = self._find(SEMIBOLD if bold else REGULAR)
			if path:
				self.cache[key] = ImageFont.truetype(path, size)
			else:
				try:
					self.cache[key] = ImageFont.load_default(size)
				except TypeError:
					self.cache[key] = ImageFont.load_default()
		return self.cache[key]


SCRATCH = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def text_width(draw, text, font):
	box = draw.textbbox((0, 0), text, font=font)
	return box[2] - box[0]


def fit(draw, text, font, width):
	if text_width(draw, text, font) <= width:
		return text
	while text and text_width(draw, text + "…", font) > width:
		text = text[:-1]
	return text.rstrip() + "…"


def background():
	column = Image.new("RGBA", (1, H))
	for y in range(H):
		t = y / (H - 1)
		column.putpixel((0, y), tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,))
	return column.resize((W, H), Image.NEAREST)


def write_bmf(path, image, x, y):
	w, h = image.size
	data = b"BMF1" + b"".join(v.to_bytes(2, "little") for v in (x, y, w, h))
	data += zlib.compress(image.convert("RGBA").tobytes("raw", "BGRA"), 6)
	with open(path, "wb") as f:
		f.write(data)
		f.flush()
		os.fsync(f.fileno())


class MenuRenderer:
	"""entries: list of dicts with slot, label, name, tag.
	strings: localized texts (title, brand, count_caption, count_unit, idle,
	starting, error, hint_move, hint_ok, hint_digits)."""

	def __init__(self, entries, strings, model="", fonts=None, timeout=99):
		self.entries = entries
		self.s = strings
		self.model = model
		self.fonts = fonts or Fonts()
		self.count_box = self._count_box(timeout)
		self.base = background()
		self._draw_header(self.base)
		n = max(1, len(entries))
		self.gap = 14 if n <= 6 else 10
		avail = LIST_BOTTOM - LIST_TOP
		self.row_h = min(96, (avail - self.gap * (n - 1)) // n)
		list_h = n * self.row_h + (n - 1) * self.gap
		self.top = LIST_TOP + max(0, (avail - list_h) // 3)

	# ------------------------------------------------------------------
	# countdown badge on the title line
	def _count_fonts(self):
		return (self.fonts.get(True, 30), self.fonts.get(True, 62), self.fonts.get(True, 32))

	def _pill_width(self, number):
		f_cap, f_num, f_unit = self._count_fonts()
		width = 30  # left padding
		caption = self.s.get("count_caption", "")
		if caption:
			width += text_width(SCRATCH, caption, f_cap) + 18
		width += text_width(SCRATCH, number, f_num)
		unit = self.s.get("count_unit", "")
		if unit:
			width += 6 + text_width(SCRATCH, unit, f_unit)
		return width + 30  # right padding

	def _count_box(self, timeout):
		"""Area of the countdown badge: the same for every count frame, so one
		frame always overwrites the previous one completely."""
		widest = max(self._pill_width(str(n)) for n in {0, 9, int(timeout) if str(timeout).isdigit() else 99})
		x = max(X0 + 320, X1 - widest - 8)
		return (x, COUNT_Y, X1 - x + 4, COUNT_H)

	def count_frame(self, seconds):
		"""seconds=None gives the empty badge (used when a key stops the countdown)."""
		x0, y0, w, h = self.count_box
		img = self.base.crop((x0, y0, x0 + w, y0 + h))
		if seconds is None:
			return img
		d = ImageDraw.Draw(img)
		f_cap, f_num, f_unit = self._count_fonts()
		number = str(int(seconds))
		last = int(seconds) <= COUNT_LAST
		bg, edge, fg, cap_col = ((COUNT_BG_LAST, COUNT_EDGE_LAST, COUNT_FG_LAST, COUNT_CAP_LAST) if last
			else (COUNT_BG, COUNT_EDGE, COUNT_FG, COUNT_CAP))
		pill_w = self._pill_width(number)
		left = w - 4 - pill_w
		top = (h - COUNT_PILL_H) // 2
		d.rounded_rectangle((left, top, left + pill_w, top + COUNT_PILL_H), radius=COUNT_PILL_H // 2, fill=bg, outline=edge, width=3)
		cy = top + COUNT_PILL_H // 2
		x = left + 30
		caption = self.s.get("count_caption", "")
		if caption:
			d.text((x, cy + 1), caption, font=f_cap, fill=cap_col, anchor="lm")
			x += text_width(d, caption, f_cap) + 18
		d.text((x, cy), number, font=f_num, fill=fg, anchor="lm")
		x += text_width(d, number, f_num)
		unit = self.s.get("count_unit", "")
		if unit:
			d.text((x + 6, cy + 6), unit, font=f_unit, fill=fg, anchor="lm")
		return img

	# ------------------------------------------------------------------
	def _title_font(self):
		reserve = (X1 - self.count_box[0]) + 40
		for size in TITLE_SIZES:
			font = self.fonts.get(True, size)
			if text_width(SCRATCH, self.s["title"], font) <= X1 - reserve - X0:
				return font
		return self.fonts.get(True, TITLE_SIZES[-1])

	def _draw_header(self, img):
		d = ImageDraw.Draw(img)
		d.text((X0, BRAND_Y), self.s["brand"], font=self.fonts.get(True, 28), fill=ACCENT_LIGHT, anchor="lm")
		title_font = self._title_font()
		d.text((X0, TITLE_Y), fit(d, self.s["title"], title_font, self.count_box[0] - 40 - X0), font=title_font, fill=HL_TEXT, anchor="lm")
		if self.model:
			# on the brand line: the title line is reserved for the countdown
			d.text((X1, BRAND_Y), self.model, font=self.fonts.get(False, 28), fill=MUTED, anchor="rm")
		d.line((X0, DIVIDER_Y, X1, DIVIDER_Y), fill=DIVIDER, width=2)

	def _row_fonts(self):
		h = self.row_h
		return (self.fonts.get(True, max(18, int(h * 0.40))),
			self.fonts.get(False, max(18, int(h * 0.40))),
			self.fonts.get(False, max(14, int(h * 0.29))),
			self.fonts.get(True, max(14, int(h * 0.34))))

	def draw_list(self, img, highlight):
		d = ImageDraw.Draw(img)
		f_label, f_name, f_tag, f_badge = self._row_fonts()
		h = self.row_h
		badge = int(h * 0.64)
		radius = max(6, int(h * 0.22))
		badge_x = X0 + 24
		label_x = badge_x + badge + 28
		label_w = max([text_width(d, e["label"], f_label) for e in self.entries] + [0])
		name_x = label_x + label_w + 40
		tag_w = max([text_width(d, e.get("tag", ""), f_tag) for e in self.entries] + [0])
		name_w = X1 - 30 - tag_w - 36 - name_x
		for i, e in enumerate(self.entries):
			y = self.top + i * (h + self.gap)
			cy = y + h // 2
			hl = i == highlight
			d.rounded_rectangle((X0, y, X1, y + h), radius=radius, fill=ACCENT if hl else ROW)
			by = cy - badge // 2
			d.rounded_rectangle((badge_x, by, badge_x + badge, by + badge), radius=max(4, badge // 5), fill=HL_TEXT if hl else BADGE)
			key = str(e["slot"]) if e["slot"] <= 9 else ""
			if key:
				d.text((badge_x + badge // 2, cy), key, font=f_badge, fill=ACCENT if hl else BADGE_TEXT, anchor="mm")
			d.text((label_x, cy), e["label"], font=f_label, fill=HL_TEXT if hl else ROW_TEXT, anchor="lm")
			d.text((name_x, cy), fit(d, e["name"], f_name, name_w), font=f_name, fill=HL_TEXT if hl else ROW_TEXT, anchor="lm")
			if e.get("tag"):
				d.text((X1 - 30, cy), e["tag"], font=f_tag, fill=HL_TAG if hl else MUTED, anchor="rm")

	# ------------------------------------------------------------------
	def _footer_base(self):
		return self.base.crop((0, FOOTER_Y, W, FOOTER_Y + FOOTER_H))

	def _hints(self, d, cy):
		f_cap = self.fonts.get(True, 26)
		f_txt = self.fonts.get(False, 28)
		groups = (("arrows", self.s["hint_move"]), ("OK", self.s["hint_ok"]), ("0-9", self.s["hint_digits"]))
		cap_h = 44
		widths = []
		for cap, label in groups:
			cap_w = 64 if cap == "arrows" else text_width(d, cap, f_cap) + 30
			widths.append((cap_w, text_width(d, label, f_txt)))
		total = sum(c + 12 + t for c, t in widths) + 40 * (len(groups) - 1)
		x = X1 - total
		left = x
		for (cap, label), (cap_w, txt_w) in zip(groups, widths):
			d.rounded_rectangle((x, cy - cap_h // 2, x + cap_w, cy + cap_h // 2), radius=9, outline=MUTED, width=2)
			if cap == "arrows":
				mx = x + cap_w // 2
				d.polygon(((mx - 21, cy + 6), (mx - 11, cy - 7), (mx - 1, cy + 6)), fill=ROW_TEXT)
				d.polygon(((mx + 1, cy - 6), (mx + 21, cy - 6), (mx + 11, cy + 7)), fill=ROW_TEXT)
			else:
				d.text((x + cap_w // 2, cy), cap, font=f_cap, fill=ROW_TEXT, anchor="mm")
			x += cap_w + 12
			d.text((x, cy), label, font=f_txt, fill=MUTED, anchor="lm")
			x += txt_w + 40
		return left

	def footer(self, kind, value=None):
		img = self._footer_base()
		d = ImageDraw.Draw(img)
		cy = FOOTER_H // 2
		f_msg = self.fonts.get(False, 34)
		f_msg_b = self.fonts.get(True, 34)
		if kind == "boot":
			if isinstance(value, int):  # an entry of the list, or a label of its own
				e = self.entries[value]
				value = "%s – %s" % (e["label"], e["name"])
			text = self.s["starting"] % value
			d.text((X0, cy), fit(d, text, f_msg_b, X1 - X0), font=f_msg_b, fill=ACCENT_LIGHT, anchor="lm")
			return img
		hints_left = self._hints(d, cy)
		width = hints_left - 50 - X0
		if kind == "idle":
			d.text((X0, cy), fit(d, self.s["idle"], f_msg, width), font=f_msg, fill=ROW_TEXT, anchor="lm")
		elif kind == "error":
			d.text((X0, cy), fit(d, self.s["error"], f_msg_b, width), font=f_msg_b, fill=ERROR, anchor="lm")
		return img

	# ------------------------------------------------------------------
	def item_frame(self, index):
		img = self.base.copy()
		self.draw_list(img, index)
		return img

	def preview(self, index, seconds, size=None):
		img = self.item_frame(index)
		img.paste(self.footer("idle"), (0, FOOTER_Y))
		img.paste(self.count_frame(seconds), (self.count_box[0], self.count_box[1]))
		img = img.convert("RGB")
		if size and tuple(size) != img.size:
			img = img.resize(tuple(size), Image.LANCZOS)
		return img

	def write_all(self, folder, timeout, signature="", recovery=None):
		"""recovery: (startup file, label) of the Recovery, written to menu.txt
		even when it is not in the list, because the menu stage falls back to
		it when the chosen image cannot be started."""
		os.makedirs(folder, exist_ok=True)
		for i in range(len(self.entries)):
			write_bmf(os.path.join(folder, "item_%d.bmf" % i), self.item_frame(i), 0, 0)
			write_bmf(os.path.join(folder, "boot_%d.bmf" % i), self.footer("boot", i), 0, FOOTER_Y)
		if recovery:
			write_bmf(os.path.join(folder, "boot_recovery.bmf"), self.footer("boot", recovery[1]), 0, FOOTER_Y)
		x, y = self.count_box[0], self.count_box[1]
		for n in range(timeout + 1):
			write_bmf(os.path.join(folder, "count_%d.bmf" % n), self.count_frame(n), x, y)
		write_bmf(os.path.join(folder, "count_off.bmf"), self.count_frame(None), x, y)
		write_bmf(os.path.join(folder, "idle.bmf"), self.footer("idle"), 0, FOOTER_Y)
		write_bmf(os.path.join(folder, "error.bmf"), self.footer("error"), 0, FOOTER_Y)
		lines = ["# MultiBootStartupMenu menu", "SIGNATURE=%s" % signature, "COUNTMAX=%d" % timeout]
		if recovery:
			lines.append("RECOVERY=%s|%s" % (recovery[0], str(recovery[1]).replace("|", "/").replace("\n", " ")))
		for e in self.entries:
			label = ("%s - %s" % (e["label"], e["name"])).replace("|", "/").replace("\n", " ")
			lines.append("ENTRY=%d|%s|%s" % (e["slot"], e["startup"], label))
		with open(os.path.join(folder, "menu.txt"), "w") as f:
			f.write("\n".join(lines) + "\n")
			f.flush()
			os.fsync(f.fileno())
