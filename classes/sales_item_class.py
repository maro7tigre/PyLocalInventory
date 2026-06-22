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
                "display_name": {"en": "Product ID", "fr": "ID Produit", "es": "ID Producto"},
                "required": False,  # allow NULL when product not yet created (Ignore path)
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
            "product_preview": {
                "display_name": {"en": "Preview", "fr": "Aperçu", "es": "Vista Previa"},
                "required": False,
                "type": "image",
                "preview_size": 50,
                "method": self.get_product_preview
            },
            "product_description":{
                "display_name": {"en": "Description", "fr": "Description", "es": "Descripción"},
                "required": False,
                "type": "string",
                "method": lambda: ""  # Placeholder for future description retrieval
            },
            "information": {
                "value": "",
                "display_name": {"en": "Information", "fr": "Information", "es": "Información"},
                "required": False,
                "default": "",
                "type": "string",
                "autocomplete": True,
                "options": self.get_service_keyword_options
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
                "product_preview": "r",
                "product_name": "rw",
                "product_description": "rw",
                "information": "rw",
                "quantity": "rw", 
                "unit_price": "rw",
                "subtotal": "r",
                "delete_action": "r"  # Delete button visible in table
            },
            "dialog": {
                "product_name": "rw",
                "product_preview": "r",
                "information": "rw",
                "quantity": "rw",
                "unit_price": "rw"
                # No delete button in dialog (use dialog's delete button instead)
            },
            "database": {
                "sales_id": "rw",
                "product_id": "rw",
                "product_name": "rw",  # snapshot of name at time of operation
                "information": "rw",
                "quantity": "rw",
                "unit_price": "rw"
                # Calculated and image parameters not stored in database
            },
            "report": {
                "product_name": "r",
                "information": "r",
                "quantity": "r",
                "unit_price": "r",
                "subtotal": "r"
                # No delete button in reports
            }
        }
    
    def get_product_options(self):
        """Return product and service keywords for autocomplete (non-empty)."""
        if not (self.database and getattr(self.database, 'cursor', None)):
            return []
        try:
            options = []
            seen = set()

            self.database.cursor.execute("SELECT name FROM Products WHERE name IS NOT NULL AND name != '' ORDER BY name")
            for row in self.database.cursor.fetchall():
                value = row[0]
                if value and value.lower() not in seen:
                    seen.add(value.lower())
                    options.append(value)

            try:
                self.database.cursor.execute(
                    "SELECT name, keywords FROM Services WHERE name IS NOT NULL AND name != '' ORDER BY name"
                )
                for service_name, keywords in self.database.cursor.fetchall():
                    for value in [service_name, *self._split_keywords(keywords or "")]:
                        if value and value.lower() not in seen:
                            seen.add(value.lower())
                            options.append(value)
            except Exception:
                pass

            return options
        except Exception:
            return []

    def get_service_keyword_options(self):
        """Return service keywords for the line-item information autocomplete."""
        if not (self.database and getattr(self.database, 'cursor', None)):
            return []

        try:
            options = []
            seen = set()
            self.database.cursor.execute(
                "SELECT keywords FROM Services WHERE keywords IS NOT NULL AND keywords != ''"
            )
            for (keywords,) in self.database.cursor.fetchall():
                for keyword in self._split_keywords(keywords or ""):
                    key = keyword.lower()
                    if key not in seen:
                        seen.add(key)
                        options.append(keyword)
            return options
        except Exception as e:
            print(f"Error getting service keyword options: {e}")
            return []
    
    def get_product_name(self):
        """Return snapshot product_name; if product_id valid, try live name; fallback to snapshot.
        This preserves entered names for unknown/deleted products.
        """
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
                # If DB name differs from snapshot (product renamed), update snapshot silently
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
            if not product_id:
                return None
            self.database.cursor.execute("SELECT preview_image FROM Products WHERE ID = ?", (product_id,))
            result = self.database.cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception as e:
            print(f"Error getting product preview: {e}")
            return None
    
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
    
    def set_value(self, param_key, value):
        """Override set_value to handle product selection updates and connected parameters"""
        # For product_name, we need to find the product and set connected parameters
        if param_key == 'product_name' and value:
            name_clean = value.strip()
            product_data = self.get_product_data_by_name(name_clean)
            if not product_data:
                service_name = self.get_service_name_by_keyword(name_clean)
                if service_name:
                    name_clean = service_name
            # Always store the typed name as snapshot even if product not found
            try:
                super().set_value('product_name', name_clean)
            except Exception:
                pass
            if product_data:
                try:
                    super().set_value('product_id', product_data['id'])
                except Exception:
                    pass
                # Auto defaults
                current_quantity = self.get_value('quantity') or 0
                if current_quantity == 0:
                    try:
                        super().set_value('quantity', 1)
                    except Exception:
                        pass
                current_price = self.get_value('unit_price') or 0.0
                if current_price == 0.0:
                    try:
                        super().set_value('unit_price', product_data['sale_price'])
                    except Exception:
                        pass
            else:
                # Unknown product: leave product_id unset (NULL) for snapshot-only save
                try:
                    if self.get_value('product_id') == 0:
                        # Clear to None so DB stores NULL instead of 0 (avoids FK issues)
                        self.parameters['product_id']['value'] = None
                except Exception:
                    pass
                # Quantity default if absent
                current_quantity = self.get_value('quantity') or 0
                if current_quantity == 0:
                    try:
                        super().set_value('quantity', 1)
                    except Exception:
                        pass
            return
        
        # Call parent set_value for other parameters
        super().set_value(param_key, value)
        
        # Handle quantity or unit_price changes to update subtotal
        if param_key in ['quantity', 'unit_price']:
            # Subtotal will be recalculated automatically via the method
            pass
    
    def get_parameter_options(self, param_key):
        """Override to provide dynamic options for product_name"""
        if param_key == 'product_name':
            return self.get_product_options()
        if param_key == 'information':
            return self.get_service_keyword_options()
        return self.parameters.get(param_key, {}).get('options', [])
    
    def get_product_data_by_name(self, product_name):
        """Get product data by name including ID and sale price"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            self.database.cursor.execute(
                "SELECT ID, sale_price, preview_image FROM Products WHERE name = ? LIMIT 1", 
                (product_name,)
            )
            result = self.database.cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'sale_price': result[1] or 0.0,
                    'preview_image': result[2]
                }
            return None
        except Exception as e:
            print(f"Error getting product data for {product_name}: {e}")
            return None

    def get_service_name_by_keyword(self, value):
        """Resolve a service name from its name or one of its stored keywords."""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None

        value_clean = (value or '').strip()
        if not value_clean:
            return None

        try:
            self.database.cursor.execute(
                "SELECT name, keywords FROM Services WHERE name IS NOT NULL AND name != ''"
            )
            for service_name, keywords in self.database.cursor.fetchall():
                candidates = [service_name, *self._split_keywords(keywords or "")]
                if any(value_clean.lower() == str(candidate).strip().lower() for candidate in candidates if candidate):
                    return service_name
        except Exception as e:
            print(f"Error resolving service keyword '{value_clean}': {e}")

        return None

    @staticmethod
    def _split_keywords(value):
        return [
            part.strip()
            for part in str(value).replace("\n", ",").split(",")
            if part.strip()
        ]
    
    def update_product_selection(self, product_name):
        """Deprecated: retained for backward compatibility; no action."""
        return None
        
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
