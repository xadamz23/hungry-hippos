"""Generate PWA icons (a hippo face on checkout green). Run: .venv/bin/python scripts/make_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
GREEN, FACE, INK, MOUTH, EAR = "#178245", "#E3F2E8", "#10291C", "#FFD84A", "#A9D6B9"


def hippo(size: int, scale: float, rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=GREEN)
    else:
        d.rectangle([0, 0, size, size], fill=GREEN)
    c = size / 2
    u = size * scale / 100  # drawing units: the face spans about 70 units

    def box(x0, y0, x1, y1):
        return [c + x0 * u, c + y0 * u, c + x1 * u, c + y1 * u]

    d.ellipse(box(-30, -40, -14, -24), fill=FACE)  # ears
    d.ellipse(box(14, -40, 30, -24), fill=FACE)
    d.ellipse(box(-26, -36, -18, -28), fill=EAR)  # inner ears
    d.ellipse(box(18, -36, 26, -28), fill=EAR)
    d.rounded_rectangle(box(-28, -30, 28, 6), radius=int(20 * u), fill=FACE)  # head
    d.rounded_rectangle(box(-36, -6, 36, 36), radius=int(20 * u), fill=FACE)  # snout
    d.ellipse(box(-15, -21, -7, -8), fill=INK)  # tall eyes, each with a glint
    d.ellipse(box(7, -21, 15, -8), fill=INK)
    d.ellipse(box(-12.5, -18, -9.5, -15), fill="#FFFFFF")
    d.ellipse(box(9.5, -18, 12.5, -15), fill="#FFFFFF")
    ring = max(2, int(1.7 * u))
    d.ellipse(box(-18.15, 1.35, -9.85, 7.65), fill=FACE, outline=INK, width=ring)  # ring nostrils
    d.ellipse(box(9.85, 1.35, 18.15, 7.65), fill=FACE, outline=INK, width=ring)
    d.chord(box(-22, 6, 22, 32), 0, 180, fill=MOUTH, outline=INK, width=max(2, int(2.5 * u)))  # mouth
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = hippo(1024, 1.05, rounded=True)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    big.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    hippo(1024, 0.8, rounded=False).resize((512, 512), Image.LANCZOS).save(OUT / "maskable-512.png")
    hippo(720, 0.95, rounded=False).resize((180, 180), Image.LANCZOS).convert("RGB").save(OUT / "apple-touch-icon.png")
    big.resize((64, 64), Image.LANCZOS).save(OUT / "favicon-64.png")


if __name__ == "__main__":
    main()
