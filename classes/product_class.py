from .base_class import BaseClass

class ProductClass(BaseClass):
    def __init__(self, id, database, name):
        super().__init__(id, database)
        self.section = "Products"
        self.parameters = {
            "id"        : { "value": id  , "display_name": {"en": "ID"            , "fr": "ID"               , "es": "ID"                 }, "required": True , "default": 0    , "options": [], "type": "int" },
            "name"      : { "value": name, "display_name": {"en": "Product Name"  , "fr": "Nom du Produit"   , "es": "Nombre del Producto"}, "required": True , "default": ""   , "options": [], "type": "string" },
            "unit_price": { "value": 0.0 , "display_name": {"en": "Unit Price"    , "fr": "Prix Unitaire"    , "es": "Precio Unitario"    }, "required": False, "default": 0.0  , "options": [], "type": "float", "unit": "MAD", "min": 0.0, "max": 999999.99 },
            "sale_price": { "value": 0.0 , "display_name": {"en": "Sale Price"    , "fr": "Prix de Vente"    , "es": "Precio de Venta"    }, "required": False, "default": 0.0  , "options": [], "type": "float", "unit": "MAD", "min": 0.0, "max": 999999.99 },
            "quantity"  : {                "display_name": {"en": "Stock Quantity", "fr": "Quantité en Stock", "es": "Cantidad en Stock"  }, "required": False, "type": "method", "method": self.calculate_quantity }
        }
        # Available parameters with read/write permissions
        self.available_parameters = {
            "table"   : { "id": "r" , "name": "r" , "unit_price": "r" , "sale_price": "r"  , "quantity": "r" },
            "dialog"  : { "id": "r" , "name": "rw", "unit_price": "rw", "sale_price": "rw" },
            "database": { "id": "rw", "name": "rw", "unit_price": "rw", "sale_price": "rw" },
            "report"  : { "id": "r" , "name": "r" , "unit_price": "r" , "sale_price": "r"  , "quantity": "r" }
        }
        
    def calculate_quantity(self):
        """Calculate current stock quantity from imports and sales"""
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