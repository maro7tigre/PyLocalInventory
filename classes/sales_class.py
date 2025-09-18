from .base_class import BaseClass

class SaleClass(BaseClass):
    def __init__(self, id, database, client_id, product_id):
        super().__init__(id, database)
        self.section = "Sales"
        self.parameters = {
            "client_id": {"value": client_id, "display name": {"en": "client", "fr": "client", "es": "cliente"}, "required": True, "default": 0, "options": [], "type": "int"},
            "product_id": {"value": product_id, "display name": {"en": "product", "fr": "produit", "es": "producto"}, "required": True, "default": 0, "options": [], "type": "int"},
            "quantity": {"value": 0, "display name": {"en": "quantity", "fr": "quantité", "es": "cantidad"}, "required": True, "default": 0, "options": [], "type": "int"},
            "unit price": {"value": 0.0, "display name": {"en": "unit price", "fr": "prix unitaire", "es": "precio unitario"}, "required": True, "default": 0.0, "options": [], "type": "float"},
            "tva": {"value": 0.0, "display name": {"en": "VAT %", "fr": "TVA %", "es": "IVA %"}, "required": False, "default": 0.0, "options": [], "type": "float"},
            "total price": {"value": 0.0, "display name": {"en": "total price", "fr": "prix total", "es": "precio total"}, "required": False, "default": 0.0, "options": [], "type": "float"},
            "date": {"value": "", "display name": {"en": "date", "fr": "date", "es": "fecha"}, "required": True, "default": "", "options": [], "type": "date"},
            "notes": {"value": "", "display name": {"en": "notes", "fr": "notes", "es": "notas"}, "required": False, "default": "", "options": [], "type": "text"}
        }
        self.available_parameters = {
            "table": ["client_id", "product_id", "quantity", "unit price", "tva", "total price", "date"],
            "dialog": ["client_id", "product_id", "quantity", "unit price", "tva", "total price", "date", "notes"],
            "database": ["client_id", "product_id", "quantity", "unit price", "tva", "total price", "date", "notes"],
            "report": ["client_id", "product_id", "quantity", "unit price", "tva", "total price", "date"]
        }
    
    def calculate_total_price(self):
        """Calculate total price including VAT"""
        unit_price = self.get_value("unit price") or 0
        quantity = self.get_value("quantity") or 0
        tva = self.get_value("tva") or 0
        
        subtotal = unit_price * quantity
        total = subtotal * (1 + tva / 100)
        self.set_value("total price", round(total, 2))
        return total