"""
Database interface - SQLite operations with parameter class integration
"""
import sqlite3
import os

class Database:
    def __init__(self, profile_manager=None, parameter_classes=None):
        self.profile_manager = profile_manager
        self.parameter_classes = parameter_classes or []
        self.sections_dictionary = {}  # Will be built from parameter classes
        self.conn = None
        self.cursor = None
        
        # Build sections dictionary from parameter classes
        self.build_sections_from_classes()
        self.refresh_connection()
    
    def build_sections_from_classes(self):
        """Build sections dictionary from parameter classes"""
        self.sections_dictionary = {}
        
        for cls in self.parameter_classes:
            try:
                # Create temporary instance to get parameter info
                temp_instance = cls(0, None)
                section_name = temp_instance.section
                
                # Get database parameters
                db_params = temp_instance.get_visible_parameters("database")
                
                # Always start with ID column
                columns = ["ID"]
                
                # Add database parameters, mapping parameter names to database column names
                for param_key in db_params:
                    if param_key in temp_instance.parameters:
                        # Map parameter names to database column names
                        if param_key == 'preview_image':
                            columns.append('preview_image')  # Use snake_case for database
                        elif param_key == 'unit_price':
                            columns.append('unit_price')
                        elif param_key == 'sale_price':
                            columns.append('sale_price')
                        elif param_key == 'client_type':
                            columns.append('client_type')
                        elif param_key == 'display_name':
                            columns.append('display_name')
                        else:
                            columns.append(param_key)
                
                self.sections_dictionary[section_name] = columns
                print(f"Built database structure for {section_name}: {columns}")
                
            except Exception as e:
                print(f"Error building section for class {cls.__name__}: {e}")
    
    def register_class(self, parameter_class):
        """Register a new parameter class"""
        if parameter_class not in self.parameter_classes:
            self.parameter_classes.append(parameter_class)
            self.build_sections_from_classes()
            # Recreate tables if database is connected
            if self.cursor:
                self.create_tables()
    
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
        """Create tables based on parameter classes"""
        if not self.cursor or not self.sections_dictionary:
            return
        
        for section, columns in self.sections_dictionary.items():
            if not columns:
                continue
                
            # Build column definitions: first column is always INTEGER PRIMARY KEY AUTOINCREMENT
            col_defs = [f"{columns[0]} INTEGER PRIMARY KEY AUTOINCREMENT"]
            # The rest are TEXT columns (we'll handle type conversion in the application layer)
            col_defs += [f"'{col}' TEXT" for col in columns[1:]]  # Quote column names for safety
            # Join all column definitions
            col_defs_str = ", ".join(col_defs)
            # Execute CREATE TABLE statement
            try:
                self.cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS '{section}' (
                    {col_defs_str}
                )
                """)
                print(f"Created/verified table: {section}")
            except sqlite3.Error as e:
                print(f"Error creating table {section}: {e}")
        
        if self.conn:
            self.conn.commit()
        
    def get_items(self, section):
        """Get all items from a section"""
        if not self.cursor or section not in self.sections_dictionary:
            print(f"Section {section} not found in database")
            return []
        
        try:
            self.cursor.execute(f"SELECT * FROM '{section}'")
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
            print(f"Cannot add item - section {section} not found")
            return False
        
        columns = self.sections_dictionary[section][1:]  # Skip ID column
        values = []
        
        # Get values in correct order, handling missing keys
        for col in columns:
            if col in data:
                values.append(data[col])
            else:
                # Handle common parameter name mappings
                if col == 'preview_image' and 'preview_image' in data:
                    values.append(data['preview_image'])
                elif col == 'unit_price' and 'unit_price' in data:
                    values.append(data['unit_price'])
                elif col == 'sale_price' and 'sale_price' in data:
                    values.append(data['sale_price'])
                else:
                    values.append('')  # Default empty value
        
        try:
            placeholders = ', '.join(['?'] * len(columns))
            columns_quoted = ', '.join([f"'{col}'" for col in columns])
            
            self.cursor.execute(
                f"INSERT INTO '{section}' ({columns_quoted}) VALUES ({placeholders})",
                values
            )
            self.conn.commit()
            print(f"Added item to {section}: {dict(zip(columns, values))}")
            return True
        except sqlite3.Error as e:
            print(f"Error adding item to {section}: {e}")
            return False

    def update_item(self, item_id, data, section):
        """Update item in a section"""
        if not self.cursor or section not in self.sections_dictionary:
            print(f"Cannot update item - section {section} not found")
            return False
        
        columns = self.sections_dictionary[section][1:]  # Skip ID column
        
        # Only update columns that are provided in data
        update_columns = []
        values = []
        
        for col in columns:
            if col in data:
                update_columns.append(col)
                values.append(data[col])
            # Handle parameter name mappings
            elif col == 'preview_image' and 'preview_image' in data:
                update_columns.append(col)
                values.append(data['preview_image'])
            elif col == 'unit_price' and 'unit_price' in data:
                update_columns.append(col)
                values.append(data['unit_price'])
            elif col == 'sale_price' and 'sale_price' in data:
                update_columns.append(col)
                values.append(data['sale_price'])
        
        if not update_columns:
            print(f"No valid columns to update for {section}")
            return False
        
        set_clauses = [f"'{col}' = ?" for col in update_columns]
        set_clause = ', '.join(set_clauses)
        values.append(item_id)  # Add ID for WHERE clause
        
        try:
            id_column = self.sections_dictionary[section][0]
            self.cursor.execute(
                f"UPDATE '{section}' SET {set_clause} WHERE '{id_column}' = ?",
                values
            )
            self.conn.commit()
            print(f"Updated item {item_id} in {section}: {dict(zip(update_columns, values[:-1]))}")
            return True
        except sqlite3.Error as e:
            print(f"Error updating item in {section}: {e}")
            return False

    def delete_item(self, item_id, section):
        """Delete item from a section"""
        if not self.cursor or section not in self.sections_dictionary:
            print(f"Cannot delete item - section {section} not found")
            return False
        
        try:
            id_column = self.sections_dictionary[section][0]
            self.cursor.execute(f"DELETE FROM '{section}' WHERE '{id_column}' = ?", (item_id,))
            self.conn.commit()
            print(f"Deleted item {item_id} from {section}")
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