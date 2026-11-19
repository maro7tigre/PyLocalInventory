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
            "department": {
                "value": "",
                "display_name": {"en": "Department", "fr": "Département", "es": "Departamento"},
                "required": True,
                "default": "",
                "options": ["sohaib cuisine", "monime porte", "omarchapa", "abd-aziiz vernise", "zohir"],
                "type": "string"
            },
            "date": {
                "value": today,
                "display_name": {"en": "Date", "fr": "Date", "es": "Fecha"},
                "required": True,
                "default": today,
                "options": [],
                "type": "date"
            },
            "report": {
                "value": "",
                "display_name": {"en": "Report", "fr": "Rapport", "es": "Informe"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "report_type": {
                "value": "General",
                "display_name": {"en": "Type", "fr": "Type", "es": "Tipo"},
                "required": False,
                "default": "General",
                "options": [
                    "General", "Sales", "Products", "Services", "Clients",
                    "Revenue", "Profit", "Activity",
                ],
                "type": "string"
            },
            "created_by": {
                "value": None, "display_name": {"en": "Created By"},
                "required": False, "default": None, "type": "int"
            },
            "created_by_username": {
                "value": "", "display_name": {"en": "Created By"},
                "required": False, "default": "", "type": "string"
            },
            "created_at": {
                "value": "", "display_name": {"en": "Created At"},
                "required": False, "default": "", "type": "date"
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
                "department": "r",
                "date": "r",
                "report_type": "r",
                "view_details": "r"
            },
            "dialog": {
                "department": "rw",
                "date": "rw",
                "report_type": "rw",
                "report": "rw",
                "created_by": "r",
                "created_by_username": "r",
                "created_at": "r"
            },
            "database": {
                "department": "rw",
                "date": "rw",
                "report_type": "rw",
                "report": "rw"
            }
        }
