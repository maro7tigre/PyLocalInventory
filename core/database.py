"""
Database interface - SQLite operations with encryption and profile management
"""
import sqlite3

class Database:
    def __init__(self, profile_manager=None, sections_dictionary=None ):
        self.profile_manager = profile_manager
        """
        sections_dictionary = {
            "Inventory": ["ID", "Company", "Role", "Product", "Price_HT", "Price_TTC", "Quantity", "Icon"],
            "Clients": ["ID", "Name", "Email", "Phone", "Address"],
            "Orders": ["ID", "Client_ID", "Product_ID", "Quantity", "Total_Price", "Date"]
        }
        """
        self.sections_dictionary = sections_dictionary
        self.refresh_connection()
        
    def refresh_connection(self):
        """Establish or refresh the database connection"""
        if self.profile_manager.selected_profile is None:
            self.conn = None
            self.cursor = None
            return
        
        
        # Placeholder for actual database connection logic
        name = self.profile_manager.selected_profile.name
        self.conn = sqlite3.connect(f'{name}.db')
        self.cursor = self.conn.cursor()
        for section, columns in self.sections_dictionary.items():
            # Build column definitions: first column is always INTEGER PRIMARY KEY AUTOINCREMENT
            col_defs = [f"{columns[0]} INTEGER PRIMARY KEY AUTOINCREMENT"]
            # The rest are TEXT columns
            col_defs += [f"{col} TEXT" for col in columns[1:]]
            # Join all column definitions
            col_defs_str = ", ".join(col_defs)
            # Execute CREATE TABLE statement
            self.cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {section} (
                {col_defs_str}
            )
            """)
        self.conn.commit()
        
    def get_items(self, section):
        pass

    def add_item(self, data, section):
        pass

    def update_item(self, item_id, data, section):
        pass

    def delete_item(self, item_id, section):
        pass