"""Invoice metadata used by the Factures management tab."""

from classes.base_class import BaseClass


class FactureClass(BaseClass):
    """Persisted invoice header; invoice lines are managed transactionally."""

    def __init__(self, id, database):
        super().__init__(id, database)
        self.section = "Factures"
        self.parameters = {
            "id": {"value": id, "display_name": {"en": "ID", "fr": "ID", "es": "ID"}, "type": "int"},
            "facture_number": {"value": "", "display_name": {"en": "Invoice N°", "fr": "Facture N°", "es": "Factura N°"}, "type": "string"},
            "client_name": {"value": "", "display_name": {"en": "Client", "fr": "Client", "es": "Cliente"}, "type": "string"},
            "date": {"value": "", "display_name": {"en": "Date", "fr": "Date", "es": "Fecha"}, "type": "date"},
            "facture_type": {"value": "normal", "display_name": {"en": "Type", "fr": "Type", "es": "Tipo"}, "type": "string"},
            "source_sale_id": {"value": None, "display_name": {"en": "Source Devis", "fr": "Devis source", "es": "Presupuesto origen"}, "type": "int"},
            "total_ht": {"value": None, "display_name": {"en": "Total HT", "fr": "Total HT", "es": "Total sin IVA"}, "type": "decimal"},
            "tva_amount": {"value": None, "display_name": {"en": "VAT", "fr": "TVA", "es": "IVA"}, "type": "decimal"},
            "total_ttc": {"value": None, "display_name": {"en": "Total TTC", "fr": "Total TTC", "es": "Total con IVA"}, "type": "decimal"},
            "notes": {"value": "", "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"}, "type": "string"},
        }
        self.available_parameters = {
            "table": {
                "id": "r", "facture_number": "r", "client_name": "r", "date": "r",
                "total_ht": "r", "tva_amount": "r", "total_ttc": "r", "facture_type": "r",
            },
            "database": {
                "facture_number": "rw", "client_name": "rw", "date": "rw", "facture_type": "rw",
                "source_sale_id": "rw", "notes": "rw",
            },
            "dialog": {"facture_number": "r", "client_name": "r", "date": "rw", "facture_type": "rw", "notes": "rw"},
        }
