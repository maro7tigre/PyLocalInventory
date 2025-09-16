from .base_class import BaseClass

class ProductClass(BaseClass):
    def __init__(self, id, database, name):
        super().__init__(id, database)
        self.section = "Products"
        self.parameters = {
            "name": {"value": name, "display name":{"fr": "nom", "es" : "nombre"} ,"required": True, "default": "", "options": [], "type": "string"},
            "unit price": {"value": 0.0, "display name":{"fr": "prix unitaire", "es" : "precio unitario"} ,"required": False, "default": 0.0, "options": [], "type": "float"},
            "sale price": {"value": 0.0, "display name":{"fr": "prix de vente", "es" : "precio de venta"} ,"required": False, "default": 0.0, "options": [], "type": "float"},
        }
        self.available_parameters = {
            "table" : ["name", "unit price", "sale price"],
            "dialog" : ["name", "unit price", "sale price"],
            "database" : ["name", "unit price", "sale price"]
        }