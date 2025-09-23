"""
Import Item Class - Represents individual items within an import operation
"""
from classes.base_class import BaseClass


class ImportItemClass(BaseClass):
    def __init__(self, id, database, import_id=0, product_id=0):
        super().__init__(id, database)
        self.section = "Import_Items"
        
        # Define all parameters with their properties
        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "import_id": {
                "value": import_id,
                "display_name": {"en": "Import ID", "fr": "ID d'Import", "es": "ID de Importación"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "product_id": {
                "value": product_id,
                "display_name": {"en": "Product", "fr": "Produit", "es": "Producto"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "quantity": {
                "value": 0,
                "display_name": {"en": "Quantity", "fr": "Quantité", "es": "Cantidad"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
                "min": 1
            },
            "unit_price": {
                "value": 0.0,
                "display_name": {"en": "Unit Price", "fr": "Prix Unitaire", "es": "Precio Unitario"},
                "required": True,
                "default": 0.0,
                "options": [],
                "type": "float",
                "min": 0.0
            },
            "subtotal": {
                "display_name": {"en": "Subtotal", "fr": "Sous-total", "es": "Subtotal"},
                "required": False,
                "type": "float",
                "method": self.calculate_subtotal
            },
            "product_preview": {
                "display_name": {"en": "Product Preview", "fr": "Aperçu Produit", "es": "Vista Previa Producto"},
                "required": False,
                "type": "image",
                "method": self.get_product_preview
            },
            "product_name": {
                "display_name": {"en": "Product Name", "fr": "Nom du Produit", "es": "Nombre del Producto"},
                "required": False,
                "type": "string",
                "method": self.get_product_name
            },
            "delete_action": {
                "display_name": {"en": "Delete", "fr": "Supprimer", "es": "Eliminar"},
                "required": False,
                "type": "action"
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "product_preview": "r",
                "product_name": "r",
                "quantity": "rw", 
                "unit_price": "rw",
                "subtotal": "r",
                "delete_action": "rw"
            },
            "dialog": {
                "product_name": "rw",
                "quantity": "rw",
                "unit_price": "rw"
            },
            "database": {
                "import_id": "rw",
                "product_id": "rw", 
                "quantity": "rw",
                "unit_price": "rw"
            },
            "report": {
                "product_id": "r",
                "quantity": "r",
                "unit_price": "r",
                "subtotal": "r"
            }
        }
    
    def calculate_subtotal(self):
        """Calculate subtotal (quantity * unit_price)"""
        quantity = self.get_value('quantity') or 0
        unit_price = self.get_value('unit_price') or 0.0
        return quantity * unit_price
    
    def get_product_name(self):
        """Get the name of the associated product"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return f"Product {self.get_value('product_id')}"
        
        try:
            product_id = self.get_value('product_id')
            self.database.cursor.execute("SELECT name FROM Products WHERE ID = ?", (product_id,))
            result = self.database.cursor.fetchone()
            return result[0] if result else f"Product {product_id}"
        except Exception as e:
            print(f"Error getting product name: {e}")
            return f"Product {self.get_value('product_id')}"
    
    def get_product_preview(self):
        """Get the preview image path of the associated product"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            product_id = self.get_value('product_id')
            self.database.cursor.execute("SELECT preview_image FROM Products WHERE ID = ?", (product_id,))
            result = self.database.cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception as e:
            print(f"Error getting product preview: {e}")
            return None
    
    def get_parameter_options(self, param_key):
        """Override to provide dynamic options for product_name"""
        if param_key == 'product_name':
            return self.get_product_options()
        return self.parameters.get(param_key, {}).get('options', [])
    
    def get_product_options(self):
        """Get list of available product names for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT name FROM Products ORDER BY name")
            results = self.database.cursor.fetchall()
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"Error getting product options: {e}")
            return []
    
    def get_product_data(self, product_name):
        """Get product data by name"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            self.database.cursor.execute("SELECT ID, name, price FROM Products WHERE name = ?", (product_name,))
            result = self.database.cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'name': result[1],
                    'price': result[2] or 0.0
                }
            return None
        except Exception as e:
            print(f"Error getting product data: {e}")
            return None
    
    def update_product_selection(self, product_name):
        """Update product_id and unit_price when product_name changes"""
        product_data = self.get_product_data(product_name)
        if product_data:
            self.set_value('product_id', product_data['id'])
            # Set unit_price to the product price if current unit_price is 0
            if self.get_value('unit_price') == 0:
                self.set_value('unit_price', product_data['price'])
    
    def set_value(self, param_key, value, destination="internal"):
        """Override to handle product_name updates"""
        # Call parent's set_value without destination parameter
        super().set_value(param_key, value)
        
        # If product_name is updated, update the product_id and unit_price
        if param_key == 'product_name' and value:
            self.update_product_selection(value)
        
    def save_to_database(self):
        """Save import item to database"""
        if not self.database:
            return False
        
        try:
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing import item
                success = self.database.update_item(self.id, data, "Import_Items")
            else:
                # Add new import item and get the new ID
                new_id = self.database.add_item(data, "Import_Items")
                if new_id:
                    self.id = new_id
                    self.set_value('id', new_id)
                    success = True
                else:
                    success = False
                
            return success
            
        except Exception as e:
            print(f"Error saving import item: {e}")
            return False