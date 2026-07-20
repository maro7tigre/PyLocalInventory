"""Deterministic report smoke test shared by source and packaged builds."""
from pathlib import Path

from classes.sales_item_class import SalesItemClass
from core.runtime_paths import user_data_root
from ui.dialogs.reports_dialog import ReportsDialog


class _Values:
    def __init__(self, values):
        self.values = values

    def get_value(self, key):
        return self.values.get(key)


def generate_verification_report():
    item = SalesItemClass(0, None)
    item.set_value('product_name', 'Porte en bois')
    item.set_value('information', 'Chene massif - finition naturelle')
    item.set_value('quantity', '2')
    item.set_value('unit_price', '1250')

    sale = _Values({
        'id': 42,
        'client_name': 'Client de verification',
        'date': '20-07-2026',
        'tva': 20,
        'information': 'Echantillon deterministe pour verification du packaging.',
    })
    sale.items = [item]
    sale.database = None

    profile = _Values({
        'company name': 'LAMIDAP SARL',
        'phone': '+212 539 39 45 60',
        'address': '288, Zone Industrielle Gzenaya, 90000 Tanger',
        'email': 'lamidap@gmail.com',
        'report footer': '',
    })
    manager = type('VerificationProfileManager', (), {'selected_profile': profile})()
    report_path = ReportsDialog(sale, manager)._generate_report_sync('devis')

    marker = Path(user_data_root()) / 'logs' / 'last_verification_report.txt'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(Path(report_path).resolve()), encoding='utf-8')
    return report_path
