"""
Sales Class - Updated to handle multiple items per sales operation
"""
from classes.base_class import BaseClass
from classes.sales_item_class import SalesItemClass


class SalesClass(BaseClass):
    def __init__(self, id, database, client_id=0):
        super().__init__(id, database)
        self.section = "Sales"
        
        # Define all parameters with their properties
        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "Sales ID", "fr": "ID de Vente", "es": "ID de Venta"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "client_id": {
                "value": client_id,
                "display_name": {"en": "Client", "fr": "Client", "es": "Cliente"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int"
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
                "default": 0.0,
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
                "method": self.get_sales_items
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
            }
        }
        
        # Define where parameters can be used and their permissions
        self.available_parameters = {
            "table": {
                "id": "r",
                "client_id": "r",
                "date": "r",
                "subtotal": "r",
                "total_price": "r"
            },
            "dialog": {
                "client_id": "rw",
                "date": "rw",
                "tva": "rw",
                "notes": "rw",
                "items": "rw"
            },
            "database": {
                "client_id": "rw",
                "date": "rw",
                "tva": "rw",
                "notes": "rw"
            },
            "report": {
                "id": "r",
                "client_id": "r",
                "date": "r",
                "tva": "r",
                "subtotal": "r",
                "total_tva": "r",
                "total_price": "r",
                "items": "r"
            }
        }
    
    def get_sales_items(self):
        """Get all items for this sales operation"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            
            # Get all sales items for this sales operation
            self.database.cursor.execute("SELECT ID FROM Sales_Items WHERE sales_id = ?", (self.id,))
            item_ids = self.database.cursor.fetchall()
            
            items = []
            for (item_id,) in item_ids:
                item = SalesItemClass(item_id, self.database)
                if item.load_database_data():
                    items.append(item)
            
            return items
            
        except Exception as e:
            print(f"Error getting sales items for sales {self.id}: {e}")
            return []
    
    def calculate_subtotal(self):
        """Calculate subtotal from all items"""
        items = self.get_sales_items()
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
        """Add an item to this sales operation"""
        if not self.database:
            return False
        
        try:
            
            # Create new sales item
            item = SalesItemClass(0, self.database, self.id, product_id)
            item.set_value('quantity', quantity)
            item.set_value('unit_price', unit_price)
            
            # Save to database
            return item.save_to_database()
            
        except Exception as e:
            print(f"Error adding item to sales {self.id}: {e}")
            return False
    
    def remove_item(self, item_id):
        """Remove an item from this sales operation"""
        if not self.database:
            return False
        
        try:
            return self.database.delete_item(item_id, "Sales_Items")
        except Exception as e:
            print(f"Error removing item {item_id} from sales {self.id}: {e}")
            return False
    
    def get_client_name(self):
        """Get the name of the associated client"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return f"Client {self.get_value('client_id')}"
        
        try:
            client_id = self.get_value('client_id')
            self.database.cursor.execute("SELECT name FROM Clients WHERE ID = ?", (client_id,))
            result = self.database.cursor.fetchone()
            return result[0] if result else f"Client {client_id}"
        except Exception as e:
            print(f"Error getting client name: {e}")
            return f"Client {self.get_value('client_id')}"

    def save_to_database(self):
        """Save sales operation to database"""
        if not self.database:
            return False
        
        try:
            # Get data for database destination  
            data = {}
            for param_key in self.get_visible_parameters("database"):
                value = self.get_value(param_key)
                data[param_key] = value
            
            if self.id and self.id > 0:
                # Update existing sales operation
                success = self.database.update_item(self.id, data, "Sales")
            else:
                # Add new sales operation and get the new ID
                new_id = self.database.add_item(data, "Sales")
                if new_id:
                    self.id = new_id
                    self.set_value('id', new_id)
                    success = True
                else:
                    success = False
                
            return success
            
        except Exception as e:
            print(f"Error saving sales operation: {e}")
            return False