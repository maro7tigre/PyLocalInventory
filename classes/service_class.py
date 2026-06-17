"""
Service Class - New entity for service management
"""
from classes.base_class import BaseClass


class ServiceClass(BaseClass):
    def __init__(self, id, database, name=""):
        super().__init__(id, database)
        self.section = "Services"
        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "service_code": {
                "value": "",
                "display_name": {"en": "Code", "fr": "Code", "es": "Código"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string",
                "unique": True
            },
            "name": {
                "value": name,
                "display_name": {"en": "Service Name", "fr": "Nom du Service", "es": "Nombre del Servicio"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "price": {
                "value": 0.0,
                "display_name": {"en": "Price", "fr": "Prix", "es": "Precio"},
                "required": False,
                "default": 0.0,
                "options": [],
                "type": "float",
                "unit": "MAD",
                "min": 0.0,
                "max": 999999.99
            },
            "preview_image": {
                "value": None,
                "display_name": {"en": "Image", "fr": "Image", "es": "Imagen"},
                "required": False,
                "default": None,
                "options": [],
                "type": "image",
                "preview_size": 100
            },
            "duration": {
                "value": "",
                "display_name": {"en": "Duration", "fr": "Durée", "es": "Duración"},
                "required": False,
                "default": "",
                "options": ["15 min", "30 min", "45 min", "1 hour", "2 hours", "Custom"],
                "type": "string"
            },
            "category": {
                "value": "",
                "display_name": {"en": "Category", "fr": "Catégorie", "es": "Categoría"},
                "required": False,
                "default": "",
                "options": ["Maintenance", "Consulting", "Repair", "Installation", "Training", "Other"],
                "type": "string"
            },
            "description": {
                "value": "",
                "display_name": {"en": "Description", "fr": "Description", "es": "Descripción"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "active": {
                "value": 1,
                "display_name": {"en": "Active", "fr": "Actif", "es": "Activo"},
                "required": False,
                "default": 1,
                "options": [],
                "type": "bool",
                "true_value": 1,
                "false_value": 0
            }
        }
        self.available_parameters = {
            "table": {
                "id": "r",
                "service_code": "r",
                "name": "r",
                "price": "r",
                "preview_image": "r",
                "category": "r"
            },
            "dialog": {
                "service_code": "rw",
                "name": "rw",
                "price": "rw",
                "preview_image": "rw",
                "category": "rw",
                "description": "rw"
            },
            "database": {
                "service_code": "rw",
                "name": "rw",
                "price": "rw",
                "preview_image": "rw",
                "duration": "rw",
                "category": "rw",
                "description": "rw",
                "active": "rw"
            },
            "report": {
                "id": "r",
                "service_code": "r",
                "name": "r",
                "price": "r",
                "category": "r",
                "description": "r"
            }
        }

    def validate_service_code_uniqueness(self, service_code):
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return True

        try:
            if self.id and self.id > 0:
                self.database.cursor.execute(
                    "SELECT COUNT(*) FROM Services WHERE service_code = ? AND ID != ?",
                    (service_code, self.id)
                )
            else:
                self.database.cursor.execute(
                    "SELECT COUNT(*) FROM Services WHERE service_code = ?",
                    (service_code,)
                )
            result = self.database.cursor.fetchone()
            return result[0] == 0 if result else True
        except Exception as e:
            print(f"Error checking service code uniqueness: {e}")
            return True

    def save_to_database(self):
        if not self.database:
            return False

        service_code = self.get_value('service_code')
        if service_code and not self.validate_service_code_uniqueness(service_code):
            print(f"Service code '{service_code}' already exists")
            return False

        return super().save_to_database()
