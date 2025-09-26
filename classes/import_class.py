"""
Import Class - Updated to handle multiple items per import operation
"""
from classes.base_class import BaseClass
from classes.import_item_class import ImportItemClass


class ImportClass(BaseClass):
    def __init__(self, id, database, supplier_id=0):
        super().__init__(id, database)
        self.section = "Imports"
        
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
            "supplier_username": {
                "value": "",
                "display_name": {"en": "Supplier", "fr": "Fournisseur", "es": "Proveedor"},
                "required": True,
                "default": "",
                "type": "string",
                "autocomplete": True,
                "options": self.get_supplier_username_options
            },
            # Snapshot copies instead of calculated methods
            "supplier_id": {
                "display_name": {"en": "Supplier ID", "fr": "ID Fournisseur", "es": "ID Proveedor"},
                "required": False,
                "type": "int"
            },
            "supplier_name": {
                "value": "",
                "display_name": {"en": "Supplier Name", "fr": "Nom du Fournisseur", "es": "Nombre del Fournisseur"},
                "required": False,
                "default": "",
                "type": "string"
            },
            "date": {
                "value": "",
                "display_name": {"en": "Date", "fr": "Date", "es": "Fecha"},
                "required": True,
                "default": "",
                "options": [],
                "type": "date"
            },
            "tva": {
                "value": 0.0,
                "display_name": {"en": "VAT %", "fr": "TVA %", "es": "IVA %"},
                "required": False,
                "default": 20.0,
                "options": [],
                "type": "float",
                "min": 0.0,
                "max": 100.0
            },
            "notes": {
                "value": "",
                "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "items": {
                "display_name": {"en": "Items", "fr": "Articles", "es": "Artículos"},
                "required": False,
                "type": "table",
                "method": self.get_import_items
            },
            "subtotal": {
                "display_name": {"en": "Subtotal", "fr": "Sous-total", "es": "Subtotal"},
                "required": False,
                "type": "float",
                "method": self.calculate_subtotal
            },
            "total_tva": {
                "display_name": {"en": "VAT Amount", "fr": "Montant TVA", "es": "Monto IVA"},
                "required": False,
                "type": "float",
                "method": self.calculate_total_tva
            },
            "total_price": {
                "display_name": {"en": "Total Price", "fr": "Prix Total", "es": "Precio Total"},
                "required": False,
                "type": "float",
                "method": self.calculate_total_price
            },
            "supplier_preview": {
                "display_name": {"en": "Image", "fr": "Image", "es": "Imagen"},
                "required": False,
                "type": "image",
                "method": self.get_supplier_preview
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "id": "r",
                "supplier_preview": "r",
                "supplier_username": "r",
                "supplier_name": "r",
                "date": "r",
                "subtotal": "r",
                "total_price": "r"
            },
            "dialog": {
                "supplier_username": "rw",
                "date": "rw",
                "tva": "rw",
                "notes": "rw",
                "items": "rw"
            },
            "database": {
                "supplier_username": "rw",
                "supplier_name": "rw",
                "date": "rw",
                "tva": "rw",
                "notes": "rw"
            },
            "report": {
                "id": "r",
                "supplier_id": "r",
                "date": "r",
                "tva": "r",
                "subtotal": "r",
                "total_tva": "r",
                "total_price": "r",
                "items": "r"
            }
        }
    
    def get_import_items(self):
        """Get all items for this import operation"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            # Get all import items for this import operation
            self.database.cursor.execute("SELECT ID FROM Import_Items WHERE import_id = ?", (self.id,))
            item_ids = self.database.cursor.fetchall()
            
            items = []
            for (item_id,) in item_ids:
                item = ImportItemClass(item_id, self.database)
                if item.load_database_data():
                    items.append(item)
            
            return items
            
        except Exception as e:
            print(f"Error getting import items for import {self.id}: {e}")
            return []
    
    def calculate_subtotal(self):
        """Calculate subtotal from all items"""
        items = self.get_import_items()
        return sum(item.get_value('subtotal') or 0 for item in items)
    
    def calculate_total_tva(self):
        """Calculate total VAT amount"""
        subtotal = self.calculate_subtotal()
        tva_percent = self.get_value('tva') or 0
        return subtotal * (tva_percent / 100)
    
    def calculate_total_price(self):
        """Calculate total price including VAT"""
        subtotal = self.calculate_subtotal()
        tva_amount = self.calculate_total_tva()
        return subtotal + tva_amount
    
    def add_item(self, product_id, quantity, unit_price):
        """Add an item to this import operation"""
        if not self.database:
            return False
        
        try:
            
            # Create new import item
            item = ImportItemClass(0, self.database, self.id, product_id)
            item.set_value('quantity', quantity)
            item.set_value('unit_price', unit_price)
            
            # Save to database
            return item.save_to_database()
            
        except Exception as e:
            print(f"Error adding item to import {self.id}: {e}")
            return False
    
    def remove_item(self, item_id):
        """Remove an item from this import operation"""
        if not self.database:
            return False
        
        try:
            return self.database.delete_item(item_id, "Import_Items")
        except Exception as e:
            print(f"Error removing item {item_id} from import {self.id}: {e}")
            return False
    
    def get_supplier_username_options(self):
        """Get list of available supplier usernames for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT username FROM Suppliers WHERE username IS NOT NULL AND username != '' ORDER BY username")
            results = self.database.cursor.fetchall()
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"Error getting supplier username options: {e}")
            return []
    
    def _refresh_supplier_snapshot(self):
        """Refresh supplier snapshot with rename-awareness (same rules as clients)."""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return
        try:
            uname = self.get_value('supplier_username')
            if not uname:
                super().set_value('supplier_id', 0)
                super().set_value('supplier_name', '')
                return
            self.database.cursor.execute("SELECT ID, name FROM Suppliers WHERE username = ?", (uname,))
            res = self.database.cursor.fetchone()
            if res:
                sid, sname = res
                current_snapshot = self.get_value('supplier_name')
                new_name = sname or uname
                if current_snapshot != new_name:
                    super().set_value('supplier_name', new_name)
                super().set_value('supplier_id', sid)
            else:
                super().set_value('supplier_id', 0)
                if not (self.get_value('supplier_name') or '').strip():
                    super().set_value('supplier_name', uname)
        except Exception as e:
            print(f"Error refreshing supplier snapshot: {e}")
    
    def get_supplier_preview(self):
        """Get the preview image path of the associated supplier"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            supplier_username = self.get_value('supplier_username')
            if not supplier_username:
                return None
            self.database.cursor.execute("SELECT preview_image FROM Suppliers WHERE username = ?", (supplier_username,))
            result = self.database.cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception as e:
            print(f"Error getting supplier preview: {e}")
            return None
    
    def set_value(self, param_key, value):
        """Override set_value to handle connected parameters"""
        # Call parent set_value first
        super().set_value(param_key, value)
        
        # Handle connected parameters for supplier_username
        if param_key == 'supplier_username':
            self._refresh_supplier_snapshot()
    
    def get_parameter_options(self, param_key):
        """Override to provide dynamic options for supplier_username"""
        if param_key == 'supplier_username':
            return self.get_supplier_options()
        return self.parameters.get(param_key, {}).get('options', [])
    
    def get_supplier_options(self):
        """Get list of available supplier usernames for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT username FROM Suppliers ORDER BY username")
            results = self.database.cursor.fetchall()
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"Error getting supplier options: {e}")
            return []
        
    def save_to_database(self):
        """Save import operation to database"""
        if not self.database:
            return False
        
        try:
            # Refresh snapshot before persisting (captures renamed suppliers)
            self._refresh_supplier_snapshot()
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing import operation
                success = self.database.update_item(self.id, data, "Imports")
            else:
                # Add new import operation and get the new ID
                new_id = self.database.add_item(data, "Imports")
                if new_id:
                    self.id = new_id
                    self.set_value('id', new_id)
                    success = True
                else:
                    success = False
                
            return success
            
        except Exception as e:
            print(f"Error saving import operation: {e}")
            return False

    def refresh_external_snapshots(self):
        """Hook for external refresh (e.g., table listing) to sync supplier name if renamed."""
        before = self.get_value('supplier_name')
        self._refresh_supplier_snapshot()
        after = self.get_value('supplier_name')
        if after != before and self.database and self.id:
            try:
                self.database.update_item(self.id, {'supplier_name': after}, 'Imports')
            except Exception as e:
                print(f"Warning: could not persist updated supplier_name snapshot for import {self.id}: {e}")