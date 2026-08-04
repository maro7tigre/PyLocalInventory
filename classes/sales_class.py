"""
Sales Class - Updated to handle multiple items per sales operation
Example showing new parameter types: date, table
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
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },

            # New: workflow state of the sale
            "state": {
                "value": "pending",  # default when created
                "display_name": {"en": "State", "fr": "État", "es": "Estado"},
                "required": False,
                "default": "pending",
                "type": "string",
                "options": ["on_hold", "pending", "confirmed", "finished"]  # internal values
            },
            # Historical sales are recorded for the books/records but never
            # touch product stock (no deduction, no validation, no movements).
            "is_historical": {
                "value": False,
                "display_name": {
                    "en": "Historical Sale", "fr": "Vente historique",
                    "es": "Venta histórica"
                },
                "required": False,
                "default": False,
                "type": "bool",
                "true_value": True,
                "false_value": False,
                "hint": {
                    "en": "Record this sale without affecting current stock",
                    "fr": "Enregistrer cette vente sans affecter le stock actuel",
                    "es": "Registrar esta venta sin afectar el stock actual"
                }
            },
            "client_username": {
                "value": "",
                "display_name": {"en": "Client", "fr": "Client", "es": "Cliente"},
                "required": True,
                "default": "",
                "type": "string",
                "autocomplete": True,
                "options": self.get_client_username_options
            },
            # Stored snapshot values (no longer calculated) so operations keep historical names
            "client_id": {
                "display_name": {"en": "Client ID", "fr": "ID Client", "es": "ID Cliente"},
                "required": False,
                "type": "int"  # not stored currently but may be populated dynamically
            },
            "client_name": {
                "value": "",
                "display_name": {"en": "Client Name", "fr": "Nom Client", "es": "Nombre Cliente"},
                "required": False,
                "default": "",
                "type": "string"  # will be set when username changes
            },
            "date": {
                "value": "",
                "display_name": {"en": "Date", "fr": "Date", "es": "Fecha"},
                "required": True,
                "default": "",
                "options": [],
                "type": "date"  # NEW: Using date type instead of string
            },
            # TVA now handled as a simple checkbox: unchecked = 0%, checked = 20%
            # Keeps database storage numeric (0 or 20) while UX is a single toggle
            "tva": {
                "value": 20.0,  # default active (was previously conceptually 20)
                "display_name": {"en": "20% VAT", "fr": "TVA 20%", "es": "IVA 20%"},
                "required": False,
                "default": 20.0,
                "type": "bool",  # custom widget mapped to numeric percent
                "true_value": 20.0,
                "false_value": 0.0
            },
            "remise": {
                "value": 0.0,
                "display_name": {"en": "Remise", "fr": "Remise", "es": "Descuento"},
                "required": False,
                "default": 0.0,
                "type": "float"
            },
            "notes": {
                "value": "",
                "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "created_by": {
                "value": None, "display_name": {"en": "Created By"},
                "required": False, "default": None, "type": "int"
            },
            "created_by_username": {
                "value": "", "display_name": {"en": "Created By"},
                "required": False, "default": "", "type": "string"
            },
            "created_at": {
                "value": "", "display_name": {"en": "Created At"},
                "required": False, "default": "", "type": "date"
            },
            "operation_token": {
                "value": "", "display_name": {"en": "Operation Token"},
                "required": False, "default": "", "type": "string"
            },
            "items": {
                "display_name": {"en": "Items", "fr": "Articles", "es": "Artículos"},
                "required": False,
                "type": "table",  # NEW: Using table type
                "method": self.get_sales_items,
                "item_class": SalesItemClass,  # Specify which item class to use
                "parent_operation": self  # Reference to parent operation
            },
            "information": {
                "display_name": {"en": "Information", "fr": "Information", "es": "Información"},
                "required": False,
                "type": "string",
                "method": self.get_sale_information
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
            "total_quantity": {
                "value": 0,
                "display_name": {"en": "Total Quantity", "fr": "Quantité Totale", "es": "Cantidad Total"},
                "required": False,
                "default": 0,
                "type": "int"
            },
            "total_production": {
                "value": 0,
                "display_name": {"en": "Total Production", "fr": "Production Totale", "es": "Producción Total"},
                "required": False,
                "default": 0,
                "type": "int"
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
                "state": "r",
                # "is_historical": "r",
                "client_name": "r",
                "notes": "r",
                "date": "r",
                "subtotal": "r",
                "remise": "r",
                "total_price": "r"
            },
            "dialog": {
                "client_username": "rw",
                "date": "rw",
                "tva": "rw",
                "notes": "rw",
                "is_historical": "rw",
                "items": "rw"  # Table parameter is editable in dialog
            },
            "database": {
                "state": "rw",
                "client_username": "rw",
                "client_id": "rw",
                "client_name": "rw",  # snapshot
                "date": "rw",
                "tva": "rw",
                "remise": "rw",
                "notes": "rw",
                "created_by": "r",
                "created_by_username": "r",
                "created_at": "r",
                "operation_token": "r"
                # Note: items are stored separately in Sales_Items table.
                # is_historical is intentionally NOT listed here: it is a real
                # BOOLEAN column managed by Database._ensure_additional_columns
                # and injected into the header by save_sale_with_items directly.
            },
            "report": {
                "id": "r",
                "state": "r",
                "is_historical": "r",
                "client_id": "r",
                "date": "r",
                "tva": "r",
                "remise": "r",
                "subtotal": "r",
                "total_tva": "r",
                "total_price": "r",
                "items": "r"
            }
        }
        # Normalize legacy / missing state after loading existing DB record
        if not self.get_value("state"):
            self.set_value("state", "pending")
    
    def get_sales_items(self):
        """Get all items for this sales operation"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        if hasattr(self, "items"):
            return self.items
        
        try:
            items = []
            for row in self.database.get_items_by_operation_id(self.id, "Sales_Items"):
                item = SalesItemClass(row.get("ID", 0), self.database)
                for key, value in row.items():
                    parameter = "id" if key == "ID" else key
                    if parameter in item.parameters and not item.is_parameter_calculated(parameter):
                        item.set_value(parameter, value)
                items.append(item)
            self.items = items
            return self.items
            
        except Exception as e:
            print(f"Error getting sales items for sales {self.id}: {e}")
            return []
    
    def calculate_subtotal(self):
        """Calculate subtotal from all items"""
        items = self.get_sales_items()
        return sum(item.get_value('subtotal') or 0 for item in items)

    def get_sale_information(self):
        """Summarize item information values for display in the sales table."""
        try:
            values = []
            seen = set()
            for item in self.get_sales_items():
                info = (item.get_value('information') or '').strip()
                if info and info.lower() not in seen:
                    seen.add(info.lower())
                    values.append(info)
            return ", ".join(values)
        except Exception as e:
            print(f"Error getting sale information for sales {self.id}: {e}")
            return ""
    
    def calculate_total_tva(self):
        """Calculate total VAT amount"""
        from decimal import Decimal
        subtotal = self.calculate_subtotal()
        remise = Decimal(str(self.get_value('remise') or 0))
        tva_percent = self.get_value('tva') or 0
        total_ht = subtotal - remise
        return total_ht * (Decimal(str(tva_percent)) / Decimal("100"))
    
    def calculate_total_price(self):
        """Calculate total price including VAT"""
        subtotal = self.calculate_subtotal()
        remise = Decimal(str(self.get_value('remise') or 0))
        tva_amount = self.calculate_total_tva()
        total_ht = subtotal - remise
        return total_ht + tva_amount
    
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
    
    def get_client_username_options(self):
        """Get list of available client usernames for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT username FROM Clients WHERE username IS NOT NULL AND username != '' ORDER BY username")
            results = self.database.cursor.fetchall()
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"Error getting client username options: {e}")
            return []
    
    def _refresh_client_snapshot(self):
        """Refresh snapshot.
        Rules:
          - If username exists in Clients table: always sync id + latest name (or fallback to username).
          - If username NOT found: preserve existing stored client_name snapshot (do NOT overwrite it), only zero client_id.
          - If snapshot empty while username present but missing: set snapshot to username once.
        This lets operations show updated names when clients are renamed, while keeping historical name if client deleted.
        """
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return
        try:
            username = self.get_value('client_username')
            if not username:
                # No username: clear id & name
                super().set_value('client_id', None)
                super().set_value('client_name', '')
                return
            self.database.cursor.execute("SELECT ID, name FROM Clients WHERE username = %s", (username,))
            res = self.database.cursor.fetchone()
            if res:
                cid, cname = res
                current_snapshot = self.get_value('client_name')
                # Update if different
                if current_snapshot != (cname or username):
                    super().set_value('client_name', cname or username)
                super().set_value('client_id', cid)
            else:
                # Client deleted/missing: keep existing snapshot (historical)
                super().set_value('client_id', None)
                if not (self.get_value('client_name') or '').strip():
                    # If we have no stored snapshot yet, fallback to username once
                    super().set_value('client_name', username)
        except Exception as e:
            print(f"Error refreshing client snapshot: {e}")
    
    def set_value(self, param_key, value):
        """Override set_value to handle connected parameters"""
        # Call parent set_value first
        super().set_value(param_key, value)
        
        # Snapshot resolution is intentionally deferred to save_to_database().
        # Running it here creates one remote query per sale while loading tabs.

    
    def get_parameter_options(self, param_key):
        """Override to provide dynamic options for client_username"""
        if param_key == 'client_username':
            return self.get_client_options()
        return self.parameters.get(param_key, {}).get('options', [])
    
    def get_client_options(self):
        """Get list of available client usernames for autocomplete"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return []
        
        try:
            self.database.cursor.execute("SELECT username FROM Clients ORDER BY username")
            results = self.database.cursor.fetchall()
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"Error getting client options: {e}")
            return []

    def save_to_database(self):
        """Save sales operation to database"""
        if not self.database:
            return False
        
        try:
            # Always refresh snapshot before persisting (captures renamed clients)
            self._refresh_client_snapshot()
            # Ensure state default
            if not self.get_value('state'):
                super().set_value('state', 'pending')

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

    def refresh_external_snapshots(self):
        """Hook called externally (e.g., on table refresh) to ensure client name stays in sync.
        If the client username still exists and its name changed, update snapshot & persist silently.
        """
        before = self.get_value('client_name')
        self._refresh_client_snapshot()
        after = self.get_value('client_name')
        if after != before and self.database and self.id:
            try:
                self.database.update_item(self.id, {'client_name': after}, 'Sales')
            except Exception as e:
                print(f"Warning: could not persist updated client_name snapshot for sale {self.id}: {e}")

