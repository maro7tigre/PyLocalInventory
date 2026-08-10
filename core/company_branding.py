"""Central company identity used by every generated report.

Single source of truth for the company contact details, logo and footer that
appear in all printed documents (devis, facture, bon de livraison, bon de
livraison import and relevé de compte client). When setting up a new company,
edit the constants below (and replace the logo file) - nothing else in the
report pipeline needs to change.
"""
import base64
import logging
import os

from core.runtime_paths import resource_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Company identity (edit here when setting up a new company)
# ---------------------------------------------------------------------------
COMPANY_NAME = "LAMIBOIS"
COMPANY_ADDRESS = "Hararin Sidi driss 35, Tanger 90000"
COMPANY_PHONE = "0661135570"
COMPANY_EMAIL = "Lamibois1@gmail.com"

# Logo embedded at the top of every report. The logo is the single canonical
# file under assets/ and is bundled with the packaged build (see
# PyLocalInventory.spec). It is resolved through the standard resource_path
# helper so it works both in source mode and inside the PyInstaller EXE.
COMPANY_LOGO_PATH = resource_path("assets", "lamibois.png")


def resolve_company_name(profile=None):
    """Company name shown on reports - always the official LAMIBOIS name.

    ``profile`` is accepted for signature compatibility only; the logged-in
    profile/username must never influence the company name.
    """
    return COMPANY_NAME.strip() or "LAMIBOIS"


def build_report_footer():
    """Clean minimal footer: company address, phone and email.

    The old legal/bank blocks (ICE, RC, Patente, CNSS, RIB...) are
    intentionally gone. Page numbers are rendered by the templates' CSS
    ``@page`` rule.
    """
    return "\n".join(
        line
        for line in (
            COMPANY_ADDRESS,
            f"Tél : {COMPANY_PHONE}",
            f"Email : {COMPANY_EMAIL}",
        )
        if line and line.strip()
    )


def get_company_logo_block():
    """Return an <img> tag embedding the company logo as a base64 data URI.

    If the canonical LAMIBOIS logo is unavailable the report renders without
    a logo (never falls back to the old LAMIDAP one) and the issue is logged.
    """
    logo_path = COMPANY_LOGO_PATH
    if not os.path.isfile(logo_path):
        logger.warning("Company logo is missing; report will render without a logo: %s", logo_path)
        return ""
    try:
        with open(logo_path, "rb") as img_f:
            b64 = base64.b64encode(img_f.read()).decode("ascii")
    except OSError as exc:
        logger.warning("Company logo could not be read; report will render without a logo: %s (%s)", logo_path, exc)
        return ""
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'class="report-logo" width="128" '
        f'style="width: 128px; height: auto; max-height: 128px; object-fit: contain; display: block; margin: 0 0 6px 0;" />'
    )
