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
            "product_name": {
                "value": "",
                "display_name": {"en": "Product", "fr": "Produit", "es": "Producto"},
                "required": True,
                "default": "",
                "type": "string",
                "autocomplete": True,
                "options": self.get_product_options
            },
            "product_id": {
                "value": product_id,
                "display_name": {"en": "Product ID", "fr": "ID Produit", "es": "ID Producto"},
                "required": False,  # allow NULL for ignored new products
                "default": 0,
                "options": [],
                "type": "int"
            },
            "product_preview": {
                "display_name": {"en": "Preview", "fr": "Aperçu", "es": "Vista Previa"},
                "required": False,
                "type": "image",
                "preview_size": 50,
                "method": self.get_product_preview
            },
            "quantity": {
                "value": 1,
                "display_name": {"en": "Quantity", "fr": "Quantité", "es": "Cantidad"},
                "required": True,
                "default": 1,
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
                "product_name": "rw",
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
    
    def get_product_options(self):
        """Return non-empty product names for autocomplete."""
        if not (self.database and getattr(self.database, 'cursor', None)):
            return []
        try:
            self.database.cursor.execute("SELECT name FROM Products WHERE name IS NOT NULL AND name != '' ORDER BY name")
            return [r[0] for r in self.database.cursor.fetchall() if r[0]]
        except Exception:
            return []
    
    def get_product_data_by_name(self, product_name):
        """Get product data by name including ID and unit price"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            self.database.cursor.execute("SELECT ID, unit_price, preview_image FROM Products WHERE name = ?", (product_name,))
            result = self.database.cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'unit_price': result[1] or 0.0,
                    'preview_image': result[2]
                }
            return None
        except Exception as e:
            print(f"Error getting product data by name: {e}")
            return None
    
    def set_value(self, param_key, value):
        """Override set_value to handle product selection updates and connected parameters"""
        # For product_name, we need to find the product and set connected parameters
        if param_key == 'product_name' and value:
            product_data = self.get_product_data_by_name(value.strip())
            if product_data:
                # Set the product_id first
                super().set_value('product_id', product_data['id'])
                
                # Set quantity to 1 if not already set or is 0
                current_quantity = self.get_value('quantity') or 0
                if current_quantity == 0:
                    super().set_value('quantity', 1)
                
                # Update price only if current price is 0 or not set
                current_price = self.get_value('unit_price') or 0.0
                if current_price == 0.0:
                    super().set_value('unit_price', product_data['unit_price'])
            return
        
        # Call parent set_value for other parameters
        super().set_value(param_key, value)
        
        # Handle quantity or unit_price changes to update subtotal
        if param_key in ['quantity', 'unit_price']:
            # Subtotal will be recalculated automatically via the method
            pass
    
    def calculate_subtotal(self):
        """Calculate subtotal (quantity * unit_price)"""
        quantity = self.get_value('quantity') or 0
        unit_price = self.get_value('unit_price') or 0.0
        return quantity * unit_price
    
    def get_product_name(self):
        """Return stored snapshot product_name; try live name if product_id valid; fallback to snapshot."""
        snapshot = self.parameters.get('product_name', {}).get('value', '') or ''
        product_id = None
        try:
            product_id = self.get_value('product_id')
        except Exception:
            pass
        if not product_id:
            return snapshot
        if not (self.database and hasattr(self.database, 'cursor') and self.database.cursor):
            return snapshot or f"Product {product_id}"
        try:
            self.database.cursor.execute("SELECT name FROM Products WHERE ID = ?", (product_id,))
            row = self.database.cursor.fetchone()
            if row and row[0]:
                if row[0] != snapshot:
                    try:
                        self.parameters['product_name']['value'] = row[0]
                    except Exception:
                        pass
                return row[0]
            return snapshot or f"Product {product_id}"
        except Exception as e:
            print(f"Error getting product name: {e}")
            return snapshot or f"Product {product_id}"
    
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
    
    def get_product_data(self, product_name):
        """Get product data by name including ID and unit price"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            self.database.cursor.execute("SELECT ID, name, unit_price FROM Products WHERE name = ?", (product_name,))
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
        """Deprecated: no-op kept for backward compatibility."""
        return None
    
    def set_value(self, param_key, value, destination="internal"):
        """Override to handle product_name updates and connected parameters (snapshot model) with nullable product_id."""
        if param_key == 'product_name' and value:
            name_clean = value.strip()
            # Always store typed product name snapshot
            try:
                super().set_value('product_name', name_clean)
            except Exception:
                pass
            product_data = self.get_product_data(name_clean)
            if product_data:
                try:
                    super().set_value('product_id', product_data['id'])
                except Exception:
                    pass
                current_quantity = self.get_value('quantity') or 0
                if current_quantity == 0:
                    try:
                        super().set_value('quantity', 1)
                    except Exception:
                        pass
                current_price = self.get_value('unit_price') or 0.0
                if current_price == 0.0:
                    try:
                        super().set_value('unit_price', product_data['price'])
                    except Exception:
                        pass
            else:
                # Unknown product: clear product_id so DB stores NULL rather than 0
                try:
                    self.parameters['product_id']['value'] = None
                except Exception:
                    pass
                current_quantity = self.get_value('quantity') or 0
                if current_quantity == 0:
                    try:
                        super().set_value('quantity', 1)
                    except Exception:
                        pass
            return

        # Fallback to parent for other params
        super().set_value(param_key, value)
        
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