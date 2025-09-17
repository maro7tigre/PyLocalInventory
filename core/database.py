"""
Database interface - SQLite operations with encryption and profile management
"""
import sqlite3
import os

class Database:
    def __init__(self, profile_manager=None, sections_dictionary=None):
        self.profile_manager = profile_manager
        """
        sections_dictionary = {
            "Inventory": ["ID", "Company", "Role", "Product", "Price_HT", "Price_TTC", "Quantity", "Icon"],
            "Clients": ["ID", "Name", "Email", "Phone", "Address"],
            "Orders": ["ID", "Client_ID", "Product_ID", "Quantity", "Total_Price", "Date"]
        }
        """
        self.sections_dictionary = sections_dictionary or {}
        self.conn = None
        self.cursor = None
        self.refresh_connection()
        
    def refresh_connection(self):
        """Establish or refresh the database connection"""
        # Close existing connection
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
        
        # Check if we have a valid profile
        if (not self.profile_manager or 
            not self.profile_manager.selected_profile or
            not hasattr(self.profile_manager.selected_profile, 'database_path')):
            return
        
        # Get database path from selected profile
        db_path = self.profile_manager.selected_profile.database_path
        
        # Ensure directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        
        # Connect to database
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        
        # Create tables if they don't exist
        self.create_tables()
    
    def create_tables(self):
        """Create tables based on sections dictionary"""
        if not self.cursor or not self.sections_dictionary:
            return
        
        for section, columns in self.sections_dictionary.items():
            if not columns:
                continue
                
            # Build column definitions: first column is always INTEGER PRIMARY KEY AUTOINCREMENT
            col_defs = [f"{columns[0]} INTEGER PRIMARY KEY AUTOINCREMENT"]
            # The rest are TEXT columns
            col_defs += [f"{col} TEXT" for col in columns[1:]]
            # Join all column definitions
            col_defs_str = ", ".join(col_defs)
            # Execute CREATE TABLE statement
            try:
                self.cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {section} (
                    {col_defs_str}
                )
                """)
            except sqlite3.Error as e:
                print(f"Error creating table {section}: {e}")
        
        if self.conn:
            self.conn.commit()
        
    def get_items(self, section):
        """Get all items from a section"""
        if not self.cursor or section not in self.sections_dictionary:
            return []
        
        try:
            self.cursor.execute(f"SELECT * FROM {section}")
            rows = self.cursor.fetchall()
            
            # Convert to list of dictionaries
            columns = self.sections_dictionary[section]
            return [dict(zip(columns, row)) for row in rows]
        except sqlite3.Error as e:
            print(f"Error getting items from {section}: {e}")
            return []

    def add_item(self, data, section):
        """Add item to a section"""
        if not self.cursor or section not in self.sections_dictionary:
            return False
        
        columns = self.sections_dictionary[section][1:]  # Skip ID column
        values = [data.get(col, '') for col in columns]
        
        try:
            placeholders = ', '.join(['?'] * len(columns))
            columns_str = ', '.join(columns)
            
            self.cursor.execute(
                f"INSERT INTO {section} ({columns_str}) VALUES ({placeholders})",
                values
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error adding item to {section}: {e}")
            return False

    def update_item(self, item_id, data, section):
        """Update item in a section"""
        if not self.cursor or section not in self.sections_dictionary:
            return False
        
        columns = self.sections_dictionary[section][1:]  # Skip ID column
        set_clause = ', '.join([f"{col} = ?" for col in columns])
        values = [data.get(col, '') for col in columns]
        values.append(item_id)  # Add ID for WHERE clause
        
        try:
            id_column = self.sections_dictionary[section][0]
            self.cursor.execute(
                f"UPDATE {section} SET {set_clause} WHERE {id_column} = ?",
                values
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error updating item in {section}: {e}")
            return False

    def delete_item(self, item_id, section):
        """Delete item from a section"""
        if not self.cursor or section not in self.sections_dictionary:
            return False
        
        try:
            id_column = self.sections_dictionary[section][0]
            self.cursor.execute(f"DELETE FROM {section} WHERE {id_column} = ?", (item_id,))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error deleting item from {section}: {e}")
            return False
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None