"""Generate a fake Dominican invoice PNG for local OCR testing."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def build_invoice(output: Path) -> None:
    width, height = 900, 1100
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    subtitle_font = load_font(24)
    body_font = load_font(22)
    small_font = load_font(19)
    total_font = load_font(30)

    draw.rectangle((35, 35, width - 35, height - 35), outline="#1F4E78", width=4)
    draw.rectangle((35, 35, width - 35, 160), fill="#1F4E78")

    draw.text((65, 65), "FERRETERÍA EL MARTILLO, SRL", font=title_font, fill="white")
    draw.text((65, 115), "RNC: 1-31-23456-7", font=subtitle_font, fill="white")

    draw.text((65, 190), "Av. 27 de Febrero #123, Santo Domingo", font=small_font, fill="#333333")
    draw.text((65, 220), "Tel.: (809) 555-0123  |  info@el-martillo.do", font=small_font, fill="#333333")

    draw.line((65, 265, width - 65, 265), fill="#999999", width=2)

    draw.text((65, 295), "FACTURA DE CRÉDITO FISCAL", font=subtitle_font, fill="#1F4E78")
    draw.text((65, 340), "NCF: B0100000123", font=body_font, fill="black")
    draw.text((65, 375), "Fecha de emisión: 05/11/2026", font=body_font, fill="black")
    draw.text((65, 410), "Cliente: Juan Pérez", font=body_font, fill="black")
    draw.text((65, 445), "RNC/Cédula: 001-1234567-8", font=body_font, fill="black")

    draw.line((65, 495, width - 65, 495), fill="#999999", width=2)

    draw.text((65, 520), "CANT", font=small_font, fill="#1F4E78")
    draw.text((150, 520), "DESCRIPCIÓN", font=small_font, fill="#1F4E78")
    draw.text((650, 520), "VALOR", font=small_font, fill="#1F4E78")

    rows = [
        ("1", "Taladro percutor 1/2 pulgada", "RD$ 2,500.00"),
        ("2", "Juego de brocas (10 piezas)", "RD$ 1,200.00"),
        ("1", "Cinta métrica 5 m", "RD$   300.00"),
    ]

    y = 565
    for quantity, description, amount in rows:
        draw.text((65, y), quantity, font=body_font, fill="black")
        draw.text((150, y), description, font=body_font, fill="black")
        draw.text((650, y), amount, font=body_font, fill="black")
        y += 50

    draw.line((65, y + 10, width - 65, y + 10), fill="#999999", width=2)

    y += 45
    draw.text((480, y), "Subtotal:", font=body_font, fill="black")
    draw.text((650, y), "RD$ 4,000.00", font=body_font, fill="black")
    y += 45
    draw.text((480, y), "ITBIS (18%):", font=body_font, fill="black")
    draw.text((650, y), "RD$   720.00", font=body_font, fill="black")

    y += 55
    draw.rectangle((450, y - 8, width - 65, y + 55), fill="#EAF1F8")
    draw.text((480, y), "TOTAL:", font=total_font, fill="#1F4E78")
    draw.text((620, y), "RD$ 4,720.00", font=total_font, fill="#1F4E78")

    draw.text((65, height - 130), "Forma de pago: Efectivo", font=body_font, fill="black")
    draw.text((65, height - 90), "¡Gracias por su compra!", font=subtitle_font, fill="#1F4E78")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    print(f"Sample invoice written to {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="sample_invoice.png", help="Output PNG path")
    args = parser.parse_args()
    build_invoice(Path(args.out))


if __name__ == "__main__":
    main()
