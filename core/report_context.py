"""Company branding for printed documents, read from the active profile.

No company data lives in the repository: every name, address, legal number,
bank detail and the logo come from the profile (local ``ProfileClass`` or the
host-supplied ``RemoteProfile`` on LAN clients). Values returned by
``company_context`` are HTML-escaped and ready to drop into the templates in
``report/``; empty profile fields simply produce no line.
"""
import base64
import html
import os

# Profile key that carries the logo bytes (base64) from the host to LAN
# clients, which have no access to the host's profile folder.
LOGO_BASE64_KEY = "logo base64"

# Profile keys shipped to LAN clients for report rendering.
REPORT_PROFILE_KEYS = (
    "company name", "activity", "address", "email", "phone", "fax", "website",
    "ice", "patente", "if number", "rc", "cnss", "bank name",
    "bank account", "bank agency", "report footer", "currency",
)


def report_profile(database=None, profile_manager=None):
    """The profile whose company details belong on printed documents.

    A LAN client still has a local profile selected (remembered from earlier
    sessions), but it prints on behalf of the host, so the host-supplied
    ``remote_profile`` always wins over the local selection.
    """
    remote = getattr(database, "remote_profile", None)
    if remote is not None:
        return remote
    manager = profile_manager or getattr(database, "profile_manager", None)
    return getattr(manager, "selected_profile", None)


def _value(profile, key):
    if profile is None:
        return ""
    try:
        value = profile.get_value(key)
    except Exception:
        return ""
    return str(value).strip() if value is not None else ""


def _esc(value):
    return html.escape(value or "")


def profile_logo_bytes(profile):
    """Return the profile's logo image bytes, or None when it has none."""
    if profile is None:
        return None
    path = getattr(profile, "preview_path", None)
    if path and os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data:
                return data
        except OSError:
            pass
    encoded = _value(profile, LOGO_BASE64_KEY)
    if encoded:
        try:
            return base64.b64decode(encoded)
        except Exception:
            return None
    return None


def profile_logo_base64(profile):
    data = profile_logo_bytes(profile)
    return base64.b64encode(data).decode("ascii") if data else ""


def _image_mime(data):
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def logo_block(profile):
    """<img> tag embedding the profile logo, or '' when none is configured."""
    data = profile_logo_bytes(profile)
    if not data:
        return ""
    b64 = base64.b64encode(data).decode("ascii")
    return (
        f'<img src="data:{_image_mime(data)};base64,{b64}" '
        f'class="report-logo" width="120" '
        f'style="width: 120px; height: auto; max-height: 80px; '
        f'object-fit: contain; display: block; margin: 0 0 6px 0;" />'
    )


def _join(parts, sep):
    return sep.join(f"{label}: {_esc(value)}" for label, value in parts if value)


def company_context(profile):
    """Template placeholders describing the company, all HTML-ready."""
    name = _value(profile, "company name")
    activity = _value(profile, "activity")
    address = _value(profile, "address")
    phone = _value(profile, "phone")
    fax = _value(profile, "fax")
    email = _value(profile, "email")
    website = _value(profile, "website")
    ice = _value(profile, "ice")
    if_number = _value(profile, "if number")
    rc = _value(profile, "rc")
    patente = _value(profile, "patente")
    cnss = _value(profile, "cnss")
    bank_name = _value(profile, "bank name")
    bank_agency = _value(profile, "bank agency")
    bank_account = _value(profile, "bank account")

    # Header contact block: one <div> per non-empty line.
    contact = [f"<div>{_esc(line.strip())}</div>" for line in address.splitlines() if line.strip()]
    for label, value in (("Tél", phone), ("Fax", fax), ("Email", email), ("Site web", website)):
        if value:
            contact.append(f"<div><strong>{label} :</strong> {_esc(value)}</div>")

    # Header legal block: identifiers on the first line, the rest below.
    legal_lines = [
        _join((("ICE", ice), ("IF", if_number), ("RC", rc)), " - "),
        _join((("Patente", patente), ("CNSS", cnss)), " - "),
    ]
    header_legal = "<br>".join(line for line in legal_lines if line)

    # Footer: company + activity, legal identifiers, bank details.
    footer = []
    title = " - ".join(_esc(part) for part in (name, activity) if part)
    if title:
        footer.append(f'<div class="footer-company">{title}</div>')
    footer_legal = _join((
        ("ICE", ice), ("PATENTE", patente), ("I.F", if_number),
        ("R.C", rc), ("CNSS", cnss),
    ), " - ")
    if footer_legal:
        footer.append(f'<div class="footer-line">{footer_legal}</div>')
    bank = ", ".join(_esc(part) for part in (bank_name, bank_agency) if part)
    if bank_account:
        bank = f"{bank} - RIB: {_esc(bank_account)}" if bank else f"RIB: {_esc(bank_account)}"
    if bank:
        footer.append(f'<div class="footer-line">{bank}</div>')

    return {
        "company_name": _esc(name),
        "company_activity": _esc(activity),
        "company_address": _esc(address),
        "company_phone": _esc(phone),
        "company_email": _esc(email),
        "company_contact_lines": "\n".join(contact),
        "company_legal": header_legal,
        "company_footer_lines": "\n".join(footer),
        "logo_block": logo_block(profile),
    }
