"""Single printable Facture document source used by preview, PDF, and print."""

import base64
import os
from html import escape

from core.calculations import calculate_line_subtotal, round_money
from core.runtime_paths import resource_path


def money(value):
    return f"{round_money(value):,.2f}".replace(",", " ").replace(".", ",")


def _profile_value(profile, key):
    return str(profile.get_value(key) or "") if profile else ""


def _logo_html():
    path = resource_path("report", "lamidap_logo.png")
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as stream:
        data = base64.b64encode(stream.read()).decode("ascii")
    return f'<img class="logo" src="data:image/png;base64,{data}">'


def build_facture_html(facture, payments, profile=None):
    """Build a white A4 business document; no application-theme styles leak in."""
    company = _profile_value(profile, "company name")
    address = _profile_value(profile, "address")
    phone = _profile_value(profile, "phone")
    email = _profile_value(profile, "email")
    footer = _profile_value(profile, "report footer")
    currency = _profile_value(profile, "currency") or "MAD"
    rows = []
    for item in facture["items"]:
        if item["item_type"] == "section":
            rows.append(f'<tr class="section"><td colspan="5">{escape(str(item["designation"]))}</td></tr>')
            continue
        total = calculate_line_subtotal(item.get("quantity") or 0, item.get("unit_price") or 0,
                                        item.get("discount_percentage") or 0)
        description = escape(str(item["designation"]))
        if item.get("information"):
            description += f'<br><span class="detail">{escape(str(item["information"]))}</span>'
        rows.append(
            "<tr><td>{}</td><td>{}</td><td class='number'>{}</td><td class='number'>{}</td>"
            "<td class='number'>{}</td></tr>".format(
                description, escape(str(item.get("unit") or "")),
                escape(str(item.get("quantity") or "")), money(item.get("unit_price") or 0), money(total)
            )
        )
    payment_rows = ""
    if facture["paid"]:
        payment_rows = f"<tr><th>AVANCE / PAYE</th><td>{money(facture['paid'])} {escape(currency)}</td></tr>"
        payment_rows += f"<tr class='grand'><th>RESTE A PAYER</th><td>{money(facture['remaining'])} {escape(currency)}</td></tr>"
    else:
        payment_rows = f"<tr class='grand'><th>NET A PAYER</th><td>{money(facture['total_ttc'])} {escape(currency)}</td></tr>"
    references = [
        f"{p.get('method')}: {money(p.get('amount') or 0)} {currency}" +
        (f" - {p['reference']}" if p.get("reference") else "")
        for p in payments if p.get("reference") or p.get("method") == "Chèque"
    ]
    source = f"Devis source : {escape(str(facture.get('source_devis') or ''))}" if facture.get("source_devis") else ""
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
        @page {{ size: A4 portrait; margin: 16mm 14mm 18mm 14mm; }}
        body {{ background:#fff; color:#161616; font-family: Arial, Helvetica, sans-serif; font-size:9pt; }}
        .header {{ width:100%; border-bottom:2px solid #202020; padding-bottom:10px; }}
        .company {{ width:58%; vertical-align:top; }} .invoice {{ width:42%; vertical-align:top; text-align:right; }}
        .logo {{ max-width:120px; max-height:65px; }} h1 {{ font-size:24pt; letter-spacing:1px; margin:0 0 8px; }}
        .muted,.detail {{ color:#555; font-size:8pt; }} .client {{ border:1px solid #333; margin:16px 0 8px; padding:9px; }}
        table {{ width:100%; border-collapse:collapse; }} .items {{ margin-top:12px; }}
        th {{ background:#e8e8e8; font-weight:bold; text-align:left; }} .items th,.items td {{ border:1px solid #555; padding:6px; }}
        .number {{ text-align:right; white-space:nowrap; }} .section td {{ background:#f0f0f0; font-weight:bold; }}
        .totals {{ width:43%; margin-left:auto; margin-top:14px; }} .totals th,.totals td {{ border:1px solid #555; padding:6px; }}
        .totals td {{ text-align:right; }} .grand th,.grand td {{ font-weight:bold; background:#e8e8e8; }}
        .words {{ margin-top:20px; border-top:1px solid #777; padding-top:9px; }} .payment {{ margin-top:9px; }}
        .footer {{ margin-top:22px; border-top:1px solid #777; padding-top:7px; text-align:center; font-size:8pt; white-space:pre-wrap; }}
    </style></head><body>
    <table class='header'><tr><td class='company'>{_logo_html()}<br><b>{escape(company)}</b><br>{escape(address)}<br>{escape(phone)}<br>{escape(email)}</td>
    <td class='invoice'><h1>FACTURE</h1><b>Numero</b> {escape(str(facture['facture_number']))}<br><b>Date</b> {escape(str(facture['date']))}</td></tr></table>
    <div class='client'><b>Mr / Societe :</b> {escape(str(facture.get('client_name') or ''))}<br>
    <b>Adresse / Ville :</b> {escape(str(facture.get('client_address') or ''))} {escape(str(facture.get('client_city') or ''))}<br>
    <b>ICE :</b> {escape(str(facture.get('client_ice') or ''))}<br>{source}</div>
    <table class='items'><thead><tr><th>Designation</th><th>Unite</th><th class='number'>Qte</th><th class='number'>Prix HT</th><th class='number'>Total HT</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    <table class='totals'><tr><th>Total HT</th><td>{money(facture['total_ht'])} {escape(currency)}</td></tr><tr><th>Total TVA</th><td>{money(facture['vat_amount'])} {escape(currency)}</td></tr><tr class='grand'><th>MONTANT GLOBAL</th><td>{money(facture['total_ttc'])} {escape(currency)}</td></tr>{payment_rows}</table>
    <p class='words'><b>Arretee la presente Facture a la somme de :</b><br>{escape(str(facture.get('amount_in_words') or ''))}</p>
    <p class='payment'>{'<br>'.join(escape(value) for value in references)}</p><div class='footer'>{escape(footer)}</div></body></html>"""
