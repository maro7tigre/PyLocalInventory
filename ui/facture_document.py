"""Deterministic Facture drawing shared by preview, PDF export, and printing."""

import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPageLayout, QPageSize, QPen

from core.calculations import calculate_line_subtotal, round_money
from core.runtime_paths import resource_path


PAGE_MARGINS_MM = QMarginsF(14, 12, 14, 14)
PRINTABLE_WIDTH_MM = 182
PREVIEW_DPI = 144


def money(value):
    return f"{round_money(value):,.2f}".replace(",", " ").replace(".", ",")


def quantity(value):
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return str(value or "")
    return f"{number:,.3f}".replace(",", " ").replace(".", ",")


def _profile_value(profile, key):
    return str(profile.get_value(key) or "") if profile else ""


def _display_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(value or "")


def configure_facture_page(printer):
    """Apply the physical A4 geometry used by every Facture output target."""
    layout = QPageLayout(
        QPageSize(QPageSize.A4), QPageLayout.Portrait, PAGE_MARGINS_MM, QPageLayout.Millimeter
    )
    printer.setPageLayout(layout)
    return printer.pageLayout()


def facture_page_geometry(layout, dpi):
    """Return page and printable rectangles in device pixels and physical millimetres."""
    return {
        "dpi": dpi,
        "page_mm": layout.fullRect(QPageLayout.Millimeter),
        "printable_mm": layout.paintRect(QPageLayout.Millimeter),
        "page_points": layout.fullRect(QPageLayout.Point),
        "printable_points": layout.paintRect(QPageLayout.Point),
        "page_px": layout.fullRectPixels(dpi),
        "printable_px": layout.paintRectPixels(dpi),
    }


def _print_layout_debug(target, geometry):
    print("[FACTURE LAYOUT DEBUG]")
    print(f"target = {target}")
    print(f"page size mm = {geometry['page_mm']}")
    print(f"printable rect mm = {geometry['printable_mm']}")
    print(f"page rect points = {geometry['page_points']}")
    print(f"printable rect points = {geometry['printable_points']}")
    print(f"page rect px = {geometry['page_px']}")
    print(f"printable rect px = {geometry['printable_px']}")
    print(f"renderer table width mm = {PRINTABLE_WIDTH_MM:.2f}")


def _document_data(facture, payments, profile):
    company = _profile_value(profile, "company name")
    address = _profile_value(profile, "address")
    phone = _profile_value(profile, "phone")
    fax = _profile_value(profile, "fax")
    email = _profile_value(profile, "email")
    website = _profile_value(profile, "website")
    currency = _profile_value(profile, "currency") or "MAD"
    report_footer = _profile_value(profile, "report footer")
    contact = [address]
    if phone:
        contact.append(f"Tél. : {phone}")
    if fax:
        contact.append(f"Fax : {fax}")
    legal_values = [
        ("ICE", _profile_value(profile, "ice")),
        ("PATENTE", _profile_value(profile, "patente")),
        ("I.F", _profile_value(profile, "if number")),
        ("R.C", _profile_value(profile, "rc")),
        ("CNSS", _profile_value(profile, "cnss")),
    ]
    legal_lines = []
    for values in (legal_values[:3], legal_values[3:]):
        line = "   ".join(f"{label}: {value}" for label, value in values if value)
        if line:
            legal_lines.append(line)
    bank_parts = [
        ("BANQUE", _profile_value(profile, "bank name")),
        ("COMPTE N°", _profile_value(profile, "bank account")),
        ("AGENCE", _profile_value(profile, "bank agency")),
    ]
    client_rows = [
        ("Mr / Société :", str(facture.get("client_name") or "")),
        ("Adresse / Ville :", " ".join(filter(None, (
            str(facture.get("client_address") or ""), str(facture.get("client_city") or ""),
        )))),
        ("ICE :", str(facture.get("client_ice") or "")),
    ]
    if facture.get("source_devis"):
        client_rows.append(("Devis N° :", str(facture["source_devis"])))
    references = []
    for payment in payments:
        if not (payment.get("reference") or payment.get("method") == "Chèque"):
            continue
        label = "CHQ" if payment.get("method") == "Chèque" else str(payment.get("method") or "Règlement").upper()
        reference = f" {payment['reference']}" if payment.get("reference") else ""
        payment_date = f" DU {_display_date(payment['date'])}" if payment.get("date") else ""
        references.append(f"{label}{reference} : {money(payment.get('amount') or 0)} {currency}{payment_date}")
    items = []
    for item in facture["items"]:
        if item["item_type"] == "section":
            items.append({"section": True, "designation": str(item["designation"])})
            continue
        total = calculate_line_subtotal(
            item.get("quantity") or 0, item.get("unit_price") or 0, item.get("discount_percentage") or 0
        )
        items.append({
            "section": False,
            "designation": str(item["designation"]),
            "information": str(item.get("information") or ""),
            "unit": str(item.get("unit") or ""),
            "quantity": quantity(item.get("quantity")),
            "price": money(item.get("unit_price") or 0),
            "total": money(total),
        })
    paid = Decimal(str(facture.get("paid") or 0))
    remaining = Decimal(str(facture.get("remaining") or 0))
    previous_advance = Decimal(str(facture.get("previous_advance_ttc") or 0))
    total_rows = [
        ("Total HT", f"{money(facture['total_ht'])} {currency}", False),
        ("Total TVA", f"{money(facture['vat_amount'])} {currency}", False),
    ]
    if facture.get("facture_type") == "balance":
        total_rows.append(("MONTANT GLOBAL", f"{money(facture.get('selected_total_ttc') or facture['total_ttc'])} {currency}", False))
        if previous_advance > 0:
            total_rows.append(("AVANCES / ACOMPTES", f"{money(previous_advance)} {currency}", False))
        total_rows.append(("RESTE À PAYER", f"{money(facture['total_ttc'])} {currency}", True))
    else:
        total_rows.append(("MONTANT GLOBAL", f"{money(facture['total_ttc'])} {currency}", True))
        if paid > 0:
            total_rows.append(("AVANCE / PAYÉ", f"{money(paid)} {currency}", False))
            if remaining > 0:
                total_rows.append(("RESTE À PAYER", f"{money(remaining)} {currency}", True))
        else:
            label = "AVANCE À PAYER" if facture.get("facture_type") == "advance" else "NET À PAYER"
            total_rows.append((label, f"{money(facture['total_ttc'])} {currency}", True))
    data = {
        "contact": "\n".join(part for part in contact if part),
        "client_rows": client_rows,
        "number": str(facture["facture_number"]),
        "date": _display_date(facture.get("date")),
        "items": items,
        "total_rows": total_rows,
        "words": str(facture.get("amount_in_words") or ""),
        "references": references,
        "notes": str(facture.get("notes") or "").strip(),
        "website": website,
        "company_contact": " - ".join(part for part in (company, f"Email : {email}" if email else "") if part),
        "legal_lines": legal_lines,
        "bank_line": " - ".join(f"{label}: {value}" for label, value in bank_parts if value),
        "report_footer": report_footer,
        "logo": QImage(resource_path("report", "lamidap_logo.png")),
    }
    return data


def _page_items(items):
    """Reserve the lower final-page area for settlement and legal footer."""
    if len(items) <= 14:
        return [(items, True)]
    pages = []
    remaining = list(items)
    while len(remaining) > 20:
        count = min(18, len(remaining) - 20)
        pages.append((remaining[:count], False))
        remaining = remaining[count:]
    pages.append((remaining, True))
    return pages


def _font(size, bold=False):
    font = QFont("Arial")
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def _draw_text(painter, rect, text, size, flags=Qt.AlignLeft | Qt.AlignVCenter, bold=False, color=Qt.black):
    painter.save()
    painter.setFont(_font(size, bold))
    painter.setPen(color)
    painter.drawText(rect, flags | Qt.TextWordWrap, text)
    painter.restore()


def _draw_box(painter, rect, fill=None, width=0.35):
    painter.save()
    painter.setPen(QPen(QColor("#222222"), width))
    painter.setBrush(QColor(fill) if fill else Qt.NoBrush)
    painter.drawRect(rect)
    painter.restore()


def _draw_facture_page(painter, printable_rect, data, page_items, is_first, is_final):
    scale = printable_rect.width() / PRINTABLE_WIDTH_MM

    def rect(x, y, width, height):
        return QRectF(printable_rect.x() + x * scale, printable_rect.y() + y * scale, width * scale, height * scale)

    def line(x1, y1, x2, y2, width=0.35):
        painter.save(); painter.setPen(QPen(QColor("#222222"), width)); painter.drawLine(
            printable_rect.x() + x1 * scale, printable_rect.y() + y1 * scale,
            printable_rect.x() + x2 * scale, printable_rect.y() + y2 * scale,
        ); painter.restore()

    if is_first:
        logo_rect = rect(0, 0, 52, 28)
        if not data["logo"].isNull():
            image = data["logo"].scaled(logo_rect.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage(QRectF(logo_rect.x(), logo_rect.y(), image.width(), image.height()), image)
        _draw_text(painter, rect(0, 30, 88, 35), data["contact"], 8.5, Qt.AlignLeft | Qt.AlignTop)
        _draw_text(painter, rect(100, 0, 82, 14), "FACTURE", 26, Qt.AlignCenter, bold=True)
        info = rect(100, 16, 82, 19)
        _draw_box(painter, info)
        line(141, 16, 141, 35)
        line(100, 24, 182, 24)
        _draw_text(painter, rect(102, 17, 37, 6), "Numéro", 9, Qt.AlignCenter, bold=True)
        _draw_text(painter, rect(143, 17, 37, 6), "Date", 9, Qt.AlignCenter, bold=True)
        _draw_text(painter, rect(102, 25, 37, 8), data["number"], 12, Qt.AlignCenter, bold=True)
        _draw_text(painter, rect(143, 25, 37, 8), data["date"], 12, Qt.AlignCenter, bold=True)
        client = rect(100, 40, 82, 33)
        _draw_box(painter, client)
        row_height = 33 / len(data["client_rows"])
        for index, (label, value) in enumerate(data["client_rows"]):
            y = 40 + index * row_height
            if index:
                line(100, y, 182, y, 0.25)
            _draw_text(painter, rect(102, y + 0.5, 27, row_height - 1), label, 8, bold=True)
            _draw_text(painter, rect(130, y + 0.5, 50, row_height - 1), value, 9.5, Qt.AlignCenter, bold=True)
        table_y = 78
    else:
        table_y = 0

    header_height = 9
    row_height = 9
    table_width = 182
    columns = (0, 98.28, 114.66, 131.04, 156.52, 182)
    _draw_box(painter, rect(0, table_y, table_width, header_height), "#303030")
    headers = ("Désignation", "Unité", "Qté", "Prix HT", "Total HT")
    for index, label in enumerate(headers):
        x = columns[index]
        width = columns[index + 1] - x
        if index:
            line(x, table_y, x, table_y + header_height)
        align = Qt.AlignLeft if index == 0 else Qt.AlignCenter
        _draw_text(painter, rect(x + 1.5, table_y, width - 3, header_height), label, 8.5, align, bold=True, color=Qt.white)

    rows_to_draw = list(page_items)
    if is_final and is_first:
        rows_to_draw.extend([None] * max(0, 13 - len(rows_to_draw)))
    for row_index, item in enumerate(rows_to_draw):
        y = table_y + header_height + row_index * row_height
        row_rect = rect(0, y, table_width, row_height)
        _draw_box(painter, row_rect, "#e8e8e8" if item and item.get("section") else None, 0.25)
        for boundary in columns[1:-1]:
            line(boundary, y, boundary, y + row_height, 0.25)
        if not item:
            continue
        if item["section"]:
            _draw_text(painter, rect(2, y, 178, row_height), item["designation"], 8.5, bold=True)
            continue
        description = item["designation"] + (f"\n{item['information']}" if item["information"] else "")
        _draw_text(painter, rect(2, y + .5, columns[1] - 4, row_height - 1), description, 8.5, Qt.AlignLeft | Qt.AlignVCenter)
        values = (item["unit"], item["quantity"], item["price"], item["total"])
        for value_index, value in enumerate(values, 1):
            x = columns[value_index]
            width = columns[value_index + 1] - x
            numeric = value_index in (2, 3, 4)
            alignment = Qt.AlignCenter if numeric or value_index == 1 else Qt.AlignRight
            _draw_text(painter, rect(x + 1, y, width - 2, row_height), value, 9.5 if numeric else 8.5, alignment)

    if not is_final:
        return
    settlement_y = table_y + header_height + len(rows_to_draw) * row_height + 5
    totals_x = 105
    total_row_height = 6
    _draw_text(painter, rect(0, settlement_y, 98, 5), "Arrêtée la présente Facture à la somme de :", 8)
    _draw_text(painter, rect(0, settlement_y + 6, 98, 11), data["words"], 9, Qt.AlignLeft | Qt.AlignTop, bold=True)
    footer_y = 244
    lower_left_y = settlement_y + 18
    lower_left_height = max(0, footer_y - lower_left_y - 1)
    if data["notes"]:
        note_height = min(10, lower_left_height)
        _draw_text(painter, rect(0, lower_left_y, 98, note_height), data["notes"], 9.5, Qt.AlignLeft | Qt.AlignTop, bold=True)
        lower_left_y += note_height + 1
        lower_left_height = max(0, footer_y - lower_left_y - 1)
    if data["references"]:
        _draw_text(painter, rect(0, lower_left_y, 98, lower_left_height), "\n".join(data["references"]), 7.5, Qt.AlignLeft | Qt.AlignTop)
    for index, (label, value, emphasized) in enumerate(data["total_rows"]):
        y = settlement_y + index * total_row_height
        fill = "#303030" if emphasized else "#eeeeee"
        _draw_box(painter, rect(totals_x, y, 77, total_row_height), fill, 0.25)
        line(totals_x + 46, y, totals_x + 46, y + total_row_height, 0.25)
        color = Qt.white if emphasized else Qt.black
        _draw_text(painter, rect(totals_x + 2, y, 42, total_row_height), label, 8, bold=emphasized, color=color)
        _draw_text(painter, rect(totals_x + 48, y, 27, total_row_height), value, 8, Qt.AlignRight, emphasized, color)
    line(0, footer_y, 182, footer_y)
    _draw_text(painter, rect(0, footer_y + 1, 182, 4), data["website"], 8, Qt.AlignCenter, bold=True)
    _draw_text(painter, rect(0, footer_y + 5, 182, 4), data["company_contact"], 6.5, Qt.AlignCenter, bold=True)
    _draw_text(painter, rect(0, footer_y + 9, 182, 7), "\n".join(data["legal_lines"]), 6.2, Qt.AlignCenter | Qt.AlignTop)
    _draw_text(painter, rect(0, footer_y + 16, 182, 4), data["bank_line"], 6.2, Qt.AlignCenter, bold=True)
    _draw_text(painter, rect(0, footer_y + 20, 182, 5), data["report_footer"], 5.8, Qt.AlignCenter | Qt.AlignTop)


def render_facture_to_printer(printer, facture, payments, profile=None):
    """Render a Facture to a QPrinter using only physical QPageLayout coordinates."""
    layout = configure_facture_page(printer)
    geometry = facture_page_geometry(layout, printer.resolution())
    _print_layout_debug("printer", geometry)
    painter = QPainter(printer)
    printer_rect = geometry["printable_px"].translated(-geometry["printable_px"].topLeft())
    print(f"printer painter viewport px = {painter.viewport()}")
    data = _document_data(facture, payments, profile)
    pages = _page_items(data["items"])
    for index, (items, final) in enumerate(pages):
        if index:
            printer.newPage()
        painter.fillRect(printer_rect, Qt.white)
        _draw_facture_page(painter, printer_rect, data, items, index == 0, final)
    painter.end()
    return geometry


def render_facture_preview_pages(facture, payments, profile=None, dpi=PREVIEW_DPI):
    """Render the same physical pages to preview images without QTextDocument."""
    layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, PAGE_MARGINS_MM, QPageLayout.Millimeter)
    geometry = facture_page_geometry(layout, dpi)
    _print_layout_debug("preview", geometry)
    data = _document_data(facture, payments, profile)
    pages = []
    for index, (items, final) in enumerate(_page_items(data["items"])):
        image = QImage(geometry["page_px"].size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        painter = QPainter(image)
        _draw_facture_page(painter, geometry["printable_px"], data, items, index == 0, final)
        painter.end()
        pages.append(image)
    return pages, geometry
