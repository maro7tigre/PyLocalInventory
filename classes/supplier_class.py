from .base_class import BaseClass

class SupplierClass(BaseClass):
    def __init__(self, id, database, name):
        super().__init__(id, database)
        self.id = id
        self.section = "Suppliers"
        self.parameters = {
            "name": {"value": name, "display name": {"en": "name", "fr": "nom", "es": "nombre"}, "required": True, "default": "", "options": [], "type": "string"},
            "display name": {"value": name, "display name": {"en": "display name", "fr": "nom d'affichage", "es": "nombre para mostrar"}, "required": False, "default": "", "options": [], "type": "string"},
            "address": {"value": "", "display name": {"en": "address", "fr": "adresse", "es": "dirección"}, "required": False, "default": "", "options": [], "type": "string"},
            "email": {"value": "", "display name": {"en": "email", "fr": "email", "es": "correo electrónico"}, "required": False, "default": "", "options": [], "type": "string"},
            "phone": {"value": "", "display name": {"en": "phone", "fr": "téléphone", "es": "teléfono"}, "required": False, "default": "", "options": [], "type": "string"},
            "notes": {"value": "", "display name": {"en": "notes", "fr": "notes", "es": "notas"}, "required": False, "default": "", "options": [], "type": "text"},
            "preview image": {"value": "", "display name": {"en": "preview image", "fr": "image d'aperçu", "es": "imagen de vista previa"}, "required": False, "default": "", "options": [], "type": "string"}
        }
        self.available_parameters = {
            "table": ["preview image", "name", "display name"],
            "dialog": ["name", "display name", "address", "email", "phone", "notes", "preview image"],
            "database": ["name", "display name", "address", "email", "phone", "notes", "preview image"],
            "operation": ["name", "display name", "preview image"],
            "report": ["name", "display name", "address", "email", "phone"]
        }
        
    def get_history(self):
        pass