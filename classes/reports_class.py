"""
Reports class - For storing department reports
"""
from classes.base_class import BaseClass
from datetime import date


class ReportsClass(BaseClass):
    def __init__(self, id, database, name=""):
        super().__init__(id, database)
        self.section = "Reports"

        today = date.today().strftime("%d-%m-%Y")

        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "Department": {
                "value": "",
                "display_name": {"en": "Department", "fr": "Département", "es": "Departamento"},
                "required": True,
                "default": "",
                "options": ["sohaib cuisine", "monime porte", "omarchapa", "abd-aziiz vernise", "zohir"],
                "type": "string"
            },
            "Date": {
                "value": today,
                "display_name": {"en": "Date", "fr": "Date", "es": "Fecha"},
                "required": True,
                "default": today,
                "options": [],
                "type": "date"
            },
            "Report": {
                "value": "",
                "display_name": {"en": "Report", "fr": "Rapport", "es": "Informe"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "view_details": {
                "value": None,
                "display_name": {"en": "Details", "fr": "Détails", "es": "Detalles"},
                "required": False,
                "default": None,
                "options": [],
                "type": "button",
                "text": "View Details",
                "color": "blue",
                "size": 32
            }
        }

        self.available_parameters = {
            "table": {
                "id": "r",
                "Department": "r",
                "Date": "r",
                "view_details": "r"
            },
            "dialog": {
                "Department": "rw",
                "Date": "rw",
                "Report": "rw"
            },
            "database": {
                "Department": "rw",
                "Date": "rw",
                "Report": "rw"
            }
        }
