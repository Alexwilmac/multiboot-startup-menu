# Translations.
#
#   python3 tools/i18n.py          update po/*.pot and po/*.po, compile the .mo
#   python3 tools/i18n.py --check  the same, but fail instead of writing
#
# po/MultiBootStartupMenu.pot  template, regenerated from the _() calls
# po/<lang>.po                 one file per language: this is what translators
#                              edit and send; en.po is kept as a copy of the
#                              English source strings
# src/MultiBootStartupMenu/locale/<lang>/LC_MESSAGES/MultiBootStartupMenu.mo
#                              compiled catalogues, the only ones the plugin
#                              needs at run time
#
# To add a language: copy po/MultiBootStartupMenu.pot to po/<code>.po, fill in
# the msgstr lines, run this script.

import ast
import gettext
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SRC = os.path.join(PROJECT, "src", "MultiBootStartupMenu")
PO = os.path.join(PROJECT, "po")
DOMAIN = "MultiBootStartupMenu"
POT = os.path.join(PO, DOMAIN + ".pot")

LANGUAGE_NAMES = {"en": "English", "it": "Italiano"}


# --- reading the sources ---------------------------------------------------
def msgids():
	ids = set()
	for path in sorted(glob.glob(os.path.join(SRC, "*.py"))):
		tree = ast.parse(open(path, encoding="utf-8").read(), path)
		for node in ast.walk(tree):
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
				arg = node.args[0]
				if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
					ids.add(arg.value)
	return ids


# --- .po files -------------------------------------------------------------
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def po_escape(text):
	return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def po_unquote(text):
	text = text.strip()
	if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
		raise ValueError("not a quoted string: %s" % text)
	text = text[1:-1]
	out = []
	i = 0
	while i < len(text):
		if text[i] == "\\" and i + 1 < len(text):
			out.append(ESCAPES.get(text[i + 1], text[i + 1]))
			i += 2
		else:
			out.append(text[i])
			i += 1
	return "".join(out)


def read_po(path):
	"""msgid -> msgstr, keeping only the entries that are actually translated."""
	entries = {}
	msgid = msgstr = None
	part = None

	def flush():
		if msgid is not None:
			entries[msgid] = msgstr or ""

	with open(path, encoding="utf-8") as f:
		for raw in f:
			line = raw.strip()
			if line.startswith("#") or (not line and part is None):
				continue
			if not line:
				flush()
				msgid = msgstr = part = None
			elif line.startswith("msgid "):
				flush()
				msgid, msgstr, part = po_unquote(line[6:]), "", "id"
			elif line.startswith("msgstr "):
				msgstr, part = po_unquote(line[7:]), "str"
			elif line.startswith('"'):
				if part == "id":
					msgid += po_unquote(line)
				elif part == "str":
					msgstr += po_unquote(line)
	flush()
	entries.pop("", None)  # the header entry
	return {k: v for k, v in entries.items() if v}


def write_po(path, language, catalog, ids, template=False):
	name = LANGUAGE_NAMES.get(language, language)
	lines = [
		"# %s translation of %s." % (name, DOMAIN) if not template else "# Translation template for %s." % DOMAIN,
		"# This file is distributed under the same licence as the plugin (GPL-2.0-only).",
		"#",
		'msgid ""',
		'msgstr ""',
		'"Project-Id-Version: %s\\n"' % DOMAIN,
		'"Language: %s\\n"' % ("" if template else language),
		'"MIME-Version: 1.0\\n"',
		'"Content-Type: text/plain; charset=UTF-8\\n"',
		'"Content-Transfer-Encoding: 8bit\\n"',
		"",
	]
	for key in sorted(ids):
		value = "" if template else catalog.get(key, "")
		if not template and not value:
			lines.append("#, fuzzy  TRANSLATE ME")
		lines.append('msgid "%s"' % po_escape(key))
		lines.append('msgstr "%s"' % po_escape(value))
		lines.append("")
	text = "\n".join(lines)
	if os.path.isfile(path) and open(path, encoding="utf-8").read() == text:
		return False
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)
	return True


# --- .mo files -------------------------------------------------------------
def write_mo(path, language, catalog):
	header = "Project-Id-Version: %s\nLanguage: %s\nMIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n" % (DOMAIN, language)
	items = sorted([("", header)] + list(catalog.items()))
	ids = b""
	strs = b""
	offsets = []
	for key, value in items:
		k = key.encode("utf-8")
		v = value.encode("utf-8")
		offsets.append((len(ids), len(k), len(strs), len(v)))
		ids += k + b"\0"
		strs += v + b"\0"
	n = len(items)
	keystart = 7 * 4 + 16 * n
	valuestart = keystart + len(ids)
	koffsets = []
	voffsets = []
	for o1, l1, o2, l2 in offsets:
		koffsets += [l1, o1 + keystart]
		voffsets += [l2, o2 + valuestart]
	output = struct.pack("Iiiiiii", 0x950412de, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
	output += struct.pack("%di" % len(koffsets), *koffsets)
	output += struct.pack("%di" % len(voffsets), *voffsets)
	output += ids + strs
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb") as f:
		f.write(output)


# --- main ------------------------------------------------------------------
def main(check=False):
	ids = msgids()
	os.makedirs(PO, exist_ok=True)
	changed = []
	if write_po(POT, "", {}, ids, template=True):
		changed.append(os.path.relpath(POT, PROJECT))

	languages = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(PO, "*.po")))
	if "en" not in languages:
		languages.append("en")
	problems = []
	for language in languages:
		path = os.path.join(PO, language + ".po")
		catalog = read_po(path) if os.path.isfile(path) else {}
		if language == "en":
			# the source strings are English: keep en.po as a plain copy of them
			catalog = {key: key for key in ids}
		missing = sorted(ids - set(catalog))
		obsolete = sorted(set(catalog) - ids)
		if missing:
			problems.append("%s: %d untranslated (%s%s)" % (language, len(missing), missing[0][:40], "..." if len(missing) > 1 else ""))
		if obsolete:
			problems.append("%s: %d no longer used" % (language, len(obsolete)))
		if write_po(path, language, catalog, ids):
			changed.append(os.path.relpath(path, PROJECT))
		catalog = {k: v for k, v in catalog.items() if k in ids}
		mo = os.path.join(SRC, "locale", language, "LC_MESSAGES", DOMAIN + ".mo")
		write_mo(mo, language, catalog)
		translations = gettext.GNUTranslations(open(mo, "rb"))
		for key, value in catalog.items():
			assert translations.gettext(key) == value, (language, key)
		print("%-3s %3d/%d messages -> %s" % (language, len(catalog), len(ids), os.path.relpath(mo, PROJECT)))

	for problem in problems:
		print("  note:", problem)
	if check and changed:
		print("out of date, run tools/i18n.py:", ", ".join(changed))
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main("--check" in sys.argv))
