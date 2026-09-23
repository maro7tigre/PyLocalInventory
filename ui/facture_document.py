"""Single printable Facture document source used by preview, PDF, and print."""

import base64
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape

from core.calculations import calculate_line_subtotal, round_money
from core.runtime_paths import resource_path


def money(value):
    return f"{round_money(value):,.2f}".replace(",", " ").replace(".", ",")


def quantity(value):
    """Keep invoice quantities precise without using money formatting."""
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return escape(str(value or ""))
    return f"{number:,.3f}".replace(",", " ").replace(".", ",")


def _profile_value(profile, key):
    return str(profile.get_value(key) or "") if profile else ""


def _html_lines(value):
    return escape(str(value or "")).replace("\n", "<br>")


def _display_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    value = str(value or "")
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return escape(value)


def _logo_html():
    path = resource_path("report", "lamidap_logo.png")
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as stream:
        data = base64.b64encode(stream.read()).decode("ascii")
    # QTextDocument honors HTML pixel dimensions for images more reliably than CSS mm units.
    return f'<img class="logo" width="180" src="data:image/png;base64,{data}">'


def _item_rows(items):
    rows = []
    for item in items:
        if item["item_type"] == "section":
            rows.append(f'<tr class="section"><td colspan="5">{escape(str(item["designation"]))}</td></tr>')
            continue
        total = calculate_line_subtotal(
            item.get("quantity") or 0, item.get("unit_price") or 0, item.get("discount_percentage") or 0
        )
        description = escape(str(item["designation"]))
        if item.get("information"):
            description += f'<br><span class="detail">{escape(str(item["information"]))}</span>'
        rows.append(
            "<tr class='item-row'><td>{}</td><td class='center'>{}</td><td class='number'>{}</td>"
            "<td class='number'>{}</td><td class='number'>{}</td></tr>".format(
                description,
                escape(str(item.get("unit") or "")),
                quantity(item.get("quantity")),
                money(item.get("unit_price") or 0),
                money(total),
            )
        )

    # A sparse invoice still needs the same ruled writing area as a paper invoice.
    for _ in range(max(0, 14 - len(rows))):
        rows.append("<tr class='filler'><td>&nbsp;</td><td></td><td></td><td></td><td></td></tr>")
    return "".join(rows)


def build_facture_html(facture, payments, profile=None):
    """Build the shared white A4 business document from the persisted invoice snapshot."""
    company = _profile_value(profile, "company name")
    address = _profile_value(profile, "address")
    phone = _profile_value(profile, "phone")
    email = _profile_value(profile, "email")
    footer = _profile_value(profile, "report footer")
    currency = _profile_value(profile, "currency") or "MAD"
    contact = "<br>".join(part for part in (
        _html_lines(address),
        f"Tél. : {escape(phone)}" if phone else "",
        f"Email : {escape(email)}" if email else "",
    ) if part)
    source = facture.get("source_devis")
    client_rows = [
        ("Mr / Société :", facture.get("client_name")),
        ("Adresse / Ville :", " ".join(filter(None, (str(facture.get("client_address") or ""), str(facture.get("client_city") or ""))))),
        ("ICE :", facture.get("client_ice")),
    ]
    if source:
        client_rows.append(("Devis N° :", source))
    client_html = "".join(
        f"<tr><th>{label}</th><td>{_html_lines(value)}</td></tr>" for label, value in client_rows
    )
    if facture["paid"]:
        payment_rows = (
            f"<tr><th>AVANCE / PAYÉ</th><td>{money(facture['paid'])} {escape(currency)}</td></tr>"
            f"<tr class='grand'><th>RESTE À PAYER</th><td>{money(facture['remaining'])} {escape(currency)}</td></tr>"
        )
    else:
        payment_rows = f"<tr class='grand'><th>NET À PAYER</th><td>{money(facture['total_ttc'])} {escape(currency)}</td></tr>"
    references = []
    for payment in payments:
        if not (payment.get("reference") or payment.get("method") == "Chèque"):
            continue
        label = "CHQ" if payment.get("method") == "Chèque" else str(payment.get("method") or "Règlement").upper()
        reference = f" {payment['reference']}" if payment.get("reference") else ""
        payment_date = f" DU {_display_date(payment['date'])}" if payment.get("date") else ""
        references.append(f"{label}{reference} : {money(payment.get('amount') or 0)} {escape(currency)}{payment_date}")
    footer_company = " - ".join(part for part in (company, f"Email : {email}" if email else "") if part)

    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
        @page {{ size: A4 portrait; margin: 12mm 14mm 14mm 14mm; }}
        * {{ box-sizing: border-box; }}
        body {{ margin:0; background:#fff; color:#111; font-family:Arial, Helvetica, sans-serif; font-size:10pt; line-height:1.25; }}
        table {{ border-collapse:collapse; width:100%; }}
        .header {{ margin-bottom:7mm; }} .company {{ width:55%; vertical-align:top; padding-right:9mm; }} .invoice {{ width:45%; vertical-align:top; }}
        .logo {{ display:block; margin:0 0 3mm; }}
        .company-name {{ font-size:13pt; font-weight:bold; letter-spacing:.3pt; }} .contact {{ margin-top:1mm; font-size:9pt; line-height:1.35; }}
        .title {{ margin:0 0 3mm; text-align:center; font-size:27pt; line-height:1; letter-spacing:1.5pt; font-weight:bold; }}
        .document-info th,.document-info td {{ border:1px solid #222; padding:2.5mm 3mm; }} .document-info th {{ width:50%; background:#303030; color:#fff; text-align:left; font-size:9pt; }}
        .document-info td {{ font-size:11pt; font-weight:bold; }}
        .client {{ width:45%; margin:0 0 6mm auto; border:1px solid #222; }} .client th,.client td {{ padding:2.1mm 3mm; vertical-align:top; }} .client th {{ width:37%; text-align:left; font-size:8.5pt; white-space:nowrap; }} .client td {{ font-weight:bold; }}
        .items {{ table-layout:fixed; margin-top:0; }} .items col.designation {{ width:54%; }} .items col.unit {{ width:9%; }} .items col.quantity {{ width:9%; }} .items col.price {{ width:14%; }} .items col.total {{ width:14%; }}
        .items thead {{ display:table-header-group; }} .items th {{ border:1px solid #222; background:#303030; color:#fff; padding:3mm 2.5mm; text-align:left; font-size:9pt; }} .items th.number {{ text-align:right; }}
        .items td {{ border-left:1px solid #333; border-right:1px solid #333; padding:2.4mm 2.5mm; vertical-align:top; }} .items tbody tr:last-child td {{ border-bottom:1px solid #333; }} .items .item-row {{ break-inside:avoid; page-break-inside:avoid; min-height:10mm; }}
        .items .filler td {{ height:10mm; }} .items .section td {{ height:auto; border-top:1px solid #333; border-bottom:1px solid #333; background:#e6e6e6; font-weight:bold; padding:2.5mm; }}
        .number {{ text-align:right; white-space:nowrap; }} .center {{ text-align:center; }} .detail {{ color:#444; font-size:8.5pt; }}
        .settlement {{ width:100%; margin-top:6mm; break-inside:avoid; page-break-inside:avoid; }} .words {{ width:55%; vertical-align:bottom; padding:0 10mm 0 1mm; }} .words-label {{ font-size:9pt; }} .words-value {{ margin-top:2.5mm; font-size:10pt; font-weight:bold; line-height:1.4; }} .references {{ margin-top:4mm; font-size:8.5pt; line-height:1.45; }}
        .totals-cell {{ width:45%; vertical-align:bottom; }} .totals th,.totals td {{ border:1px solid #222; padding:2.5mm 3mm; }} .totals th {{ background:#eee; text-align:left; }} .totals td {{ text-align:right; white-space:nowrap; }} .totals .grand th,.totals .grand td {{ background:#303030; color:#fff; font-weight:bold; }}
        .footer {{ margin-top:7mm; border-top:1px solid #333; padding-top:2.5mm; text-align:center; font-size:8pt; line-height:1.35; white-space:normal; }} .footer-company {{ font-weight:bold; margin-bottom:1mm; }} .footer-details {{ white-space:pre-wrap; }}
    </style></head><body>
    <table class='header'><tr><td class='company'>{_logo_html()}<div class='company-name'>{escape(company)}</div><div class='contact'>{contact}</div></td><td class='invoice'><h1 class='title'>FACTURE</h1><table class='document-info'><tr><th>Numéro</th><th>Date</th></tr><tr><td>{escape(str(facture['facture_number']))}</td><td>{_display_date(facture.get('date'))}</td></tr></table></td></tr></table>
    <table class='client'>{client_html}</table>
    <table class='items'><colgroup><col class='designation'><col class='unit'><col class='quantity'><col class='price'><col class='total'></colgroup><thead><tr><th>Désignation</th><th class='center'>Unité</th><th class='number'>Qté</th><th class='number'>Prix HT</th><th class='number'>Total HT</th></tr></thead><tbody>{_item_rows(facture['items'])}</tbody></table>
    <table class='settlement'><tr><td class='words'><div class='words-label'>Arrêtée la présente Facture à la somme de :</div><div class='words-value'>{_html_lines(facture.get('amount_in_words'))}</div><div class='references'>{'<br>'.join(escape(value) for value in references)}</div></td><td class='totals-cell'><table class='totals'><tr><th>Total HT</th><td>{money(facture['total_ht'])} {escape(currency)}</td></tr><tr><th>Total TVA</th><td>{money(facture['vat_amount'])} {escape(currency)}</td></tr><tr class='grand'><th>MONTANT GLOBAL</th><td>{money(facture['total_ttc'])} {escape(currency)}</td></tr>{payment_rows}</table></td></tr></table>
    <div class='footer'><div class='footer-company'>{escape(footer_company)}</div><div class='footer-details'>{_html_lines(footer)}</div></div>
    </body></html>"""
