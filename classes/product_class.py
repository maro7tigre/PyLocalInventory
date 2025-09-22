"""
Product Class - Works with the database system
"""
from classes.base_class import BaseClass


class ProductClass(BaseClass):
    def __init__(self, id, database, name=""):
        super().__init__(id, database)
        self.section = "Products"
        
        # Define all parameters with their properties
        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,  # ID is auto-generated
                "default": 0,
                "options": [],
                "type": "int"
            },
            "name": {
                "value": name,
                "display_name": {"en": "Product Name", "fr": "Nom du Produit", "es": "Nombre del Producto"},
                "required": True,
                "default": "",
                "options": ["iron", "wood", "wool", "steel", "aluminum", "plastic"],
                "type": "string"
            },
            "unit_price": {
                "value": 0.0,
                "display_name": {"en": "Unit Price", "fr": "Prix Unitaire", "es": "Precio Unitario"},
                "required": False,
                "default": 0.0,
                "options": [],
                "type": "float",
                "unit": "MAD",
                "min": 0.0,
                "max": 999999.99
            },
            "sale_price": {
                "value": 0.0,
                "display_name": {"en": "Sale Price", "fr": "Prix de Vente", "es": "Precio de Venta"},
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
                "display_name": {"en": "Product Image", "fr": "Image du Produit", "es": "Imagen del Producto"},
                "required": False,
                "default": None,
                "options": [],
                "type": "image",
                "preview_size": 100
            },
            "category": {
                "value": "",
                "display_name": {"en": "Category", "fr": "Catégorie", "es": "Categoría"},
                "required": False,
                "default": "",
                "options": ["Electronics", "Clothing", "Food", "Books", "Tools", "Raw Materials", "Other"],
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
            "quantity": {
                "display_name": {"en": "Stock Quantity", "fr": "Quantité en Stock", "es": "Cantidad en Stock"},
                "required": False,
                "type": "int",
                "method": self.calculate_quantity  # This makes it calculated
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "id": "r",
                "preview_image": "r",
                "name": "rw",
                "unit_price": "r",
                "sale_price": "r", 
                "quantity": "r",
                "category": "r"
            },
            "dialog": {
                "name": "rw",
                "unit_price": "rw",
                "sale_price": "rw",
                "preview_image": "rw",
                "category": "rw",
                "description": "rw"
            },
            "database": {
                "name": "rw",
                "unit_price": "rw", 
                "sale_price": "rw",
                "preview_image": "rw",
                "category": "rw",
                "description": "rw"
                # Note: quantity is calculated and not stored in database
                # Note: id is handled automatically by database
            },
            "report": {
                "id": "r",
                "name": "r",
                "unit_price": "r",
                "sale_price": "r",
                "quantity": "r",
                "category": "r",
                "description": "r"
            }
        }
    
    def calculate_quantity(self):
        """Calculate current stock quantity from imports and sales"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return 0
        
        try:
            # Get total imports for this product
            self.database.cursor.execute("SELECT SUM(quantity) FROM Imports WHERE product_id = ?", (self.id,))
            imports_result = self.database.cursor.fetchone()
            total_imports = imports_result[0] if imports_result and imports_result[0] else 0
            
            # Get total sales for this product  
            self.database.cursor.execute("SELECT SUM(quantity) FROM Sales WHERE product_id = ?", (self.id,))
            sales_result = self.database.cursor.fetchone()
            total_sales = sales_result[0] if sales_result and sales_result[0] else 0
            
            return int(total_imports - total_sales)
        except Exception as e:
            print(f"Error calculating quantity for product {self.id}: {e}")
            return 0
    
    def get_profit_margin(self):
        """Calculate profit margin percentage"""
        unit_price = self.get_value('unit_price') or 0
        sale_price = self.get_value('sale_price') or 0
        
        if unit_price == 0:
            return 0
        
        return ((sale_price - unit_price) / unit_price) * 100
    
    def is_low_stock(self, threshold=5):
        """Check if product is low on stock"""
        return self.get_value('quantity') <= threshold
    
    def get_total_value(self):
        """Get total inventory value (quantity * unit_price)"""
        quantity = self.get_value('quantity') or 0
        unit_price = self.get_value('unit_price') or 0
        return quantity * unit_price
    
    def load_database_data(self):
        """Load product data from database"""
        if not self.database or not self.id:
            return False
        
        try:
            # Get raw data from database
            items = self.database.get_items("Products")
            for item in items:
                if str(item.get('ID', '')) == str(self.id):
                    # Load all non-calculated parameters
                    for param_key in self.parameters:
                        if not self.is_parameter_calculated(param_key) and param_key in item:
                            try:
                                # Handle field name mapping if needed
                                if param_key == 'id':
                                    value = item.get('ID', 0)
                                else:
                                    value = item.get(param_key)
                                
                                if value is not None:
                                    self.set_value(param_key, value)
                            except (KeyError, ValueError) as e:
                                print(f"Warning: Could not load {param_key}: {e}")
                    return True
            return False
                
        except Exception as e:
            print(f"Error loading product data for ID {self.id}: {e}")
            return False
    
    def save_to_database(self):
        """Save product to database"""
        if not self.database:
            return False
        
        try:
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing product
                success = self.database.update_item(self.id, data, "Products")
            else:
                # Add new product
                success = self.database.add_item(data, "Products")
                
            return success
            
        except Exception as e:
            print(f"Error saving product: {e}")
            return False