"""Generate FinCore app icons and splash screens for Android, iOS and desktop from one design."""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

FE = "/home/user/Fincore/frontend"
GREEN, DARK, GOLD = (4, 120, 87), (11, 31, 23), (250, 204, 21)
FONT = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
if not os.path.exists(FONT):
    FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def icon(size, rounded=True, pad=0.0):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inset = int(size * pad)
    box = (inset, inset, size - inset, size - inset)
    if rounded:
        d.rounded_rectangle(box, radius=int((size - 2 * inset) * 0.22), fill=GREEN)
    else:
        d.rectangle(box, fill=GREEN)
    f = ImageFont.truetype(FONT, int((size - 2 * inset) * 0.62))
    d.text((size / 2, size / 2), "F", font=f, fill=GOLD, anchor="mm")
    return img

def splash(w, h):
    img = Image.new("RGB", (w, h), DARK)
    s = int(min(w, h) * 0.28)
    i = icon(s)
    img.paste(i, ((w - s) // 2, (h - s) // 2), i)
    return img

icon(1024).save(f"{FE}/resources/icon.png")
splash(2732, 2732).save(f"{FE}/resources/splash.png")

# Android launcher icons (legacy + round + adaptive foreground)
res = f"{FE}/android/app/src/main/res"
for dpi, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    d = f"{res}/mipmap-{dpi}"
    os.makedirs(d, exist_ok=True)
    icon(px).save(f"{d}/ic_launcher.png")
    icon(px).save(f"{d}/ic_launcher_round.png")
    fg = Image.new("RGBA", (int(px * 2.25),) * 2, (0, 0, 0, 0))
    inner = icon(int(px * 1.5), rounded=False)
    fg.paste(inner, ((fg.width - inner.width) // 2,) * 2, inner)
    fg.save(f"{d}/ic_launcher_foreground.png")
bg = f"{res}/values/ic_launcher_background.xml"
if os.path.exists(bg):
    open(bg, "w").write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#047857</color>\n</resources>\n')
for folder in os.listdir(res):
    if folder.startswith("drawable"):
        p = f"{res}/{folder}/splash.png"
        if os.path.exists(p):
            w, h = Image.open(p).size
            splash(w, h).save(p)

# iOS app icon + splash
ios = f"{FE}/ios/App/App/Assets.xcassets"
if os.path.isdir(ios):
    ai = f"{ios}/AppIcon.appiconset"
    for name in os.listdir(ai):
        if name.endswith(".png"):
            w, _ = Image.open(f"{ai}/{name}").size
            icon(w, rounded=False).convert("RGB").save(f"{ai}/{name}")
    sp = f"{ios}/Splash.imageset"
    if os.path.isdir(sp):
        for name in os.listdir(sp):
            if name.endswith(".png"):
                w, h = Image.open(f"{sp}/{name}").size
                splash(w, h).save(f"{sp}/{name}")
print("icons generated")
