import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from MultiBootStartupMenu.render import MenuRenderer, Fonts, FOOTER_Y
FONTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "obh", "data", "fonts"))
strings = {
    "brand": "VU+ MULTIBOOT",
    "title": "Scegli l'immagine da avviare",
    "count_caption": "Avvio tra",
    "count_unit": "s",
    "idle": "Premi OK per avviare l'immagine evidenziata",
    "starting": "Avvio di %s…",
    "error": "Questa immagine non si può avviare (assente o incompleta)",
    "hint_move": "Scegli", "hint_ok": "Avvia", "hint_digits": "Avvio diretto",
}
entries = [
    {"slot": 0, "startup": "STARTUP_RECOVERY", "label": "Recovery", "name": "OpenBh 5.6 (01-05-2026)", "tag": "eMMC"},
    {"slot": 1, "startup": "STARTUP_1", "label": "Slot 1", "name": "OpenBH 6.0.002 (13-09-2026)", "tag": "eMMC"},
    {"slot": 2, "startup": "STARTUP_2", "label": "Slot 2", "name": "OpenATV 7.6 (05-08-2026)", "tag": "eMMC"},
    {"slot": 3, "startup": "STARTUP_3", "label": "Slot 3", "name": "OpenBH 6.0.003 (27-09-2026)", "tag": "eMMC"},
]
r = MenuRenderer(entries, strings, "Vu+ Ultimo4K", Fonts((FONTS,)), timeout=10)
out = sys.argv[1]
r.preview(3, 10).save(out)
r.preview(3, 3).save(out.replace(".png", "_last3.png"))
img = r.item_frame(3); img.paste(r.footer("boot", 3), (0, FOOTER_Y)); img.convert("RGB").save(out.replace(".png", "_boot.png"))
img = r.item_frame(0); img.paste(r.footer("idle"), (0, FOOTER_Y)); img.convert("RGB").save(out.replace(".png", "_idle.png"))
print("ok: countdown area", r.count_box)
