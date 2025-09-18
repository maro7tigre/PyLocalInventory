from .base_class import BaseClass

class ProductClass(BaseClass):
    def __init__(self, id, database, name):
        super().__init__(id, database)
        self.section = "Products"
        self.parameters = {
            "name": {"value": name, "display name": {"en": "name", "fr": "nom", "es": "nombre"}, "required": True, "default": "", "options": [], "type": "string"},
            "unit price": {"value": 0.0, "display name": {"en": "unit price", "fr": "prix unitaire", "es": "precio unitario"}, "required": False, "default": 0.0, "options": [], "type": "float"},
            "sale price": {"value": 0.0, "display name": {"en": "sale price", "fr": "prix de vente", "es": "precio de venta"}, "required": False, "default": 0.0, "options": [], "type": "float"},
        }
        self.available_parameters = {
            "table": ["name", "unit price", "sale price"],
            "dialog": ["name", "unit price", "sale price"],
            "database": ["name", "unit price", "sale price"],
            "operation": ["name"],
            "report": ["name", "unit price", "sale price"]
        }
        
    def get_quantity(self):
        """Calculate quantity from imports and sales in database"""
        if not self.database or not self.database.cursor:
            return 0
        
        try:
            # Get total imports for this product
            self.database.cursor.execute("SELECT SUM(quantity) FROM Imports WHERE product_id = ?", (self.id,))
            imports_result = self.database.cursor.fetchone()
            total_imports = imports_result[0] if imports_result[0] else 0
            
            # Get total sales for this product
            self.database.cursor.execute("SELECT SUM(quantity) FROM Sales WHERE product_id = ?", (self.id,))
            sales_result = self.database.cursor.fetchone()
            total_sales = sales_result[0] if sales_result[0] else 0
            
            return total_imports - total_sales
        except Exception as e:
            print(f"Error calculating quantity for product {self.id}: {e}")
            return 0
    
    def get_history(self):
        pass