"""
Supplier Class - Updated to match ProductClass parameter system
"""
from classes.base_class import BaseClass


class SupplierClass(BaseClass):
    def __init__(self, id, database, name=""):
        super().__init__(id, database)
        self.section = "Suppliers"
        
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
                "display_name": {"en": "Supplier Name", "fr": "Nom du Fournisseur", "es": "Nombre del Proveedor"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "display_name": {
                "value": name,
                "display_name": {"en": "Display Name", "fr": "Nom d'Affichage", "es": "Nombre para Mostrar"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "address": {
                "value": "",
                "display_name": {"en": "Address", "fr": "Adresse", "es": "Dirección"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "email": {
                "value": "",
                "display_name": {"en": "Email", "fr": "Email", "es": "Correo Electrónico"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "phone": {
                "value": "",
                "display_name": {"en": "Phone", "fr": "Téléphone", "es": "Teléfono"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "notes": {
                "value": "",
                "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "preview_image": {
                "value": None,
                "display_name": {"en": "Supplier Logo", "fr": "Logo du Fournisseur", "es": "Logo del Proveedor"},
                "required": False,
                "default": None,
                "options": [],
                "type": "image",
                "preview_size": 100
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "id": "r",
                "preview_image": "r",
                "name": "rw",
                "display_name": "r"
            },
            "dialog": {
                "name": "rw",
                "display_name": "rw",
                "address": "rw",
                "email": "rw",
                "phone": "rw",
                "notes": "rw",
                "preview_image": "rw"
            },
            "database": {
                "name": "rw",
                "display_name": "rw",
                "address": "rw",
                "email": "rw",
                "phone": "rw",
                "notes": "rw",
                "preview_image": "rw"
                # Note: id is handled automatically by database
            },
            "report": {
                "id": "r",
                "name": "r",
                "display_name": "r",
                "address": "r",
                "email": "r",
                "phone": "r"
            }
        }
    
    def get_supplier_transactions(self):
        """Get all transactions (imports) from this supplier"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            # Get all imports from this supplier
            self.database.cursor.execute("SELECT * FROM Imports WHERE supplier_id = ?", (self.id,))
            return self.database.cursor.fetchall()
        except Exception as e:
            print(f"Error getting transactions for supplier {self.id}: {e}")
            return []
    
    def get_total_supplied(self):
        """Calculate total amount supplied by this supplier"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return 0.0
        
        try:
            # Get total from imports
            self.database.cursor.execute("SELECT SUM(total_price) FROM Imports WHERE supplier_id = ?", (self.id,))
            result = self.database.cursor.fetchone()
            return float(result[0]) if result and result[0] else 0.0
        except Exception as e:
            print(f"Error calculating total supplied for supplier {self.id}: {e}")
            return 0.0
    
    def get_last_supply_date(self):
        """Get the date of the last supply"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return None
        
        try:
            # Get most recent import date
            self.database.cursor.execute("SELECT date FROM Imports WHERE supplier_id = ? ORDER BY date DESC LIMIT 1", (self.id,))
            result = self.database.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting last supply date for supplier {self.id}: {e}")
            return None
    
    def get_supplied_products(self):
        """Get list of products supplied by this supplier"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            # Get unique products from this supplier
            self.database.cursor.execute("""
                SELECT DISTINCT p.name, p.ID 
                FROM Products p 
                JOIN Imports i ON p.ID = i.product_id 
                WHERE i.supplier_id = ?
            """, (self.id,))
            return self.database.cursor.fetchall()
        except Exception as e:
            print(f"Error getting supplied products for supplier {self.id}: {e}")
            return []
    
    def load_database_data(self):
        """Load supplier data from database"""
        if not self.database or not self.id:
            return False
        
        try:
            # Get raw data from database
            items = self.database.get_items("Suppliers")
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
            print(f"Error loading supplier data for ID {self.id}: {e}")
            return False
    
    def save_to_database(self):
        """Save supplier to database"""
        if not self.database:
            return False
        
        try:
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing supplier
                success = self.database.update_item(self.id, data, "Suppliers")
            else:
                # Add new supplier
                success = self.database.add_item(data, "Suppliers")
                
            return success
            
        except Exception as e:
            print(f"Error saving supplier: {e}")
            return False