"""
Sales Item Class - Represents individual items within a sales operation
Updated example showing button parameter for delete actions
"""
from classes.base_class import BaseClass


class SalesItemClass(BaseClass):
    def __init__(self, id, database, sales_id=0, product_id=0):
        super().__init__(id, database)
        self.section = "Sales_Items"
        
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
            "sales_id": {
                "value": sales_id,
                "display_name": {"en": "Sales ID", "fr": "ID de Vente", "es": "ID de Venta"},
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
            "delete_action": {
                "display_name": {"en": "Delete", "fr": "Supprimer", "es": "Eliminar"},
                "required": False,
                "type": "button",  # NEW: Button parameter type
                "text": "🗑️",  # Trash emoji
                "color": "red",  # Red styling
                "size": 25,  # Button size
                "action": self.delete_self  # Method to call when clicked
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "product_id": "rw",
                "quantity": "rw", 
                "unit_price": "rw",
                "subtotal": "r",
                "delete_action": "r"  # Delete button visible in table
            },
            "dialog": {
                "product_id": "rw",
                "quantity": "rw",
                "unit_price": "rw"
                # No delete button in dialog (use dialog's delete button instead)
            },
            "database": {
                "sales_id": "rw",
                "product_id": "rw", 
                "quantity": "rw",
                "unit_price": "rw"
                # Calculated and button parameters not stored in database
            },
            "report": {
                "product_id": "r",
                "quantity": "r",
                "unit_price": "r",
                "subtotal": "r"
                # No delete button in reports
            }
        }
    
    def calculate_subtotal(self):
        """Calculate subtotal (quantity * unit_price)"""
        quantity = self.get_value('quantity') or 0
        unit_price = self.get_value('unit_price') or 0.0
        return quantity * unit_price
    
    def delete_self(self):
        """Delete this item from database - called by delete button"""
        if self.database and self.id:
            try:
                success = self.database.delete_item(self.id, self.section)
                if success:
                    print(f"Successfully deleted sales item {self.id}")
                    return True
                else:
                    print(f"Failed to delete sales item {self.id}")
                    return False
            except Exception as e:
                print(f"Error deleting sales item {self.id}: {e}")
                return False
        return False
    
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
    
    def get_product_options(self):
        """Get list of available products for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT ID, name FROM Products ORDER BY name")
            results = self.database.cursor.fetchall()
            return [f"{row[0]} - {row[1]}" for row in results]
        except Exception as e:
            print(f"Error getting product options: {e}")
            return []
        
    def save_to_database(self):
        """Save sales item to database"""
        if not self.database:
            return False
        
        try:
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing sales item
                success = self.database.update_item(self.id, data, "Sales_Items")
            else:
                # Add new sales item and get the new ID
                new_id = self.database.add_item(data, "Sales_Items")
                if new_id:
                    self.id = new_id
                    self.set_value('id', new_id)
                    success = True
                else:
                    success = False
                
            return success
            
        except Exception as e:
            print(f"Error saving sales item: {e}")
            return False