"""Generate PWA icons (a coral hippo in Lagoon water). Run: .venv/bin/python scripts/make_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
CORAL, MUZZLE, DARK_CORAL, PUPIL = "#FF8A6B", "#FFAB94", "#B93F2C", "#06121F"
SKY = ((0x0A, 0x2F, 0x52), (0x0C, 0x4A, 0x5E))
WATER = ((0x22, 0xC7, 0xD6), (0x03, 0x69, 0xA1))
MASTER = 2048
U = MASTER / 512  # drawing units: a 512 × 512 canvas


def bezier(p0, p1, p2, p3, steps=64):
    points = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t**2 * (1 - t), t**3
        points.append(((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]) * U, (a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]) * U))
    return points


def gradient(start, end, value) -> Image.Image:
    """A gradient across the master image; value(x, y) gives the position along it, in 0-1 at 1/8 resolution."""
    size = MASTER // 8
    img = Image.new("RGB", (size, size))
    for y in range(size):
        for x in range(size):
            t = min(1, max(0, value(x / size * 512, y / size * 512)))
            img.putpixel((x, y), tuple(round(a + (b - a) * t) for a, b in zip(start, end)))
    return img.resize((MASTER, MASTER), Image.BICUBIC)


def hippo() -> Image.Image:
    """The square, full-bleed art. All of the hippo is inside the maskable safe zone."""
    img = gradient(*SKY, lambda x, y: (x + y) / 1024)
    d = ImageDraw.Draw(img)

    def circle(x, y, r, fill):
        d.ellipse([(x - r) * U, (y - r) * U, (x + r) * U, (y + r) * U], fill=fill)

    for x in (170, 342):  # ears, tucked slightly behind the head
        circle(x, 130, 30, CORAL)
        circle(x, 130, 13, DARK_CORAL)
    circle(256, 212, 106, CORAL)  # head
    d.rectangle([150 * U, 212 * U, 362 * U, 400 * U], fill=CORAL)
    for x, pupil in ((212, 217), (300, 295)):  # eyes, looking slightly inward
        circle(x, 176, 28, "#FFFFFF")
        circle(pupil, 179, 14, PUPIL)
    circle(184, 316, 92, MUZZLE)  # two-lobed muzzle
    circle(328, 316, 92, MUZZLE)
    for x in (190, 322):  # nostrils
        d.ellipse([(x - 18) * U, (292 - 14) * U, (x + 18) * U, (292 + 14) * U], fill=DARK_CORAL)

    wave = (
        bezier((0, 352), (64, 322), (128, 322), (192, 352))
        + bezier((192, 352), (256, 382), (320, 382), (384, 352))
        + bezier((384, 352), (448, 322), (480, 326), (512, 338))
    )
    mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(mask).polygon(wave + [(MASTER, MASTER), (0, MASTER)], fill=255)
    img.paste(gradient(*WATER, lambda x, y: (y - 329.5) / 282.5), mask=mask)

    ripple = bezier((150, 426), (180, 412), (210, 412), (240, 426)) + bezier((240, 426), (270, 440), (300, 440), (330, 426))
    mask = Image.new("L", (MASTER, MASTER), 0)
    m = ImageDraw.Draw(mask)
    for x, y in ripple:  # a line of dots: PIL's thick curved lines come out jagged
        m.ellipse([x - 8 * U, y - 8 * U, x + 8 * U, y + 8 * U], fill=140)
    img.paste("#FFFFFF", mask=mask)
    return img


def rounded(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=int(img.width * 0.22), fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    art = hippo()
    big = rounded(art)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    big.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    big.resize((64, 64), Image.LANCZOS).save(OUT / "favicon-64.png")
    art.resize((512, 512), Image.LANCZOS).save(OUT / "maskable-512.png")
    art.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")


if __name__ == "__main__":
    main()
