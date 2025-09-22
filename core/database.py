"""
Database System - Updated to support multi-item operations with foreign keys
"""
import sqlite3
import os


class Database:
    """Database that integrates with parameter class system"""
    
    def __init__(self, profile_manager=None):
        self.profile_manager = profile_manager
        self.registered_classes = {}  # section_name -> class
        self.conn = None
        self.cursor = None
        
    def register_class(self, cls):
        """Register a parameter class with the database"""
        try:
            # Create temporary instance to get metadata
            temp_obj = cls(0, None)  # Pass None for database to avoid circular dependency
            section_name = temp_obj.section
            
            self.registered_classes[section_name] = cls
            
            # Create/update database table for this class if connected
            if self.cursor:
                self._create_table_for_class(cls, section_name)
                
            print(f"✓ Registered parameter class: {section_name}")
            return True
            
        except Exception as e:
            print(f"✗ Failed to register {cls.__name__}: {e}")
            return False
    
    def connect(self):
        """Establish database connection using profile manager"""
        if not self.profile_manager or not self.profile_manager.selected_profile:
            print("No profile selected, cannot connect to database")
            return False
            
        # Close existing connection
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
        
        try:
            # Get database path from profile
            db_path = self.profile_manager.selected_profile.database_path
            
            # Ensure directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
            
            # Connect to database
            self.conn = sqlite3.connect(db_path)
            self.cursor = self.conn.cursor()
            
            # Enable foreign key support in SQLite
            self.cursor.execute("PRAGMA foreign_keys = ON")
            
            # Create tables for all registered classes
            self._create_all_tables()
            
            print(f"✓ Connected to database: {db_path}")
            return True
            
        except Exception as e:
            print(f"✗ Failed to connect to database: {e}")
            return False
    
    def _create_table_for_class(self, cls, section_name):
        """Create database table for a parameter class with foreign key support"""
        try:
            # Create temporary instance to get parameter info
            temp_obj = cls(0, None)
            
            # Get parameters that should be stored in database
            db_params = temp_obj.get_visible_parameters("database")
            
            if not db_params:
                print(f"No database parameters defined for {section_name}")
                return
            
            # Build column definitions
            columns = ["ID INTEGER PRIMARY KEY AUTOINCREMENT"]
            foreign_keys = []
            
            for param_key in db_params:
                if param_key in temp_obj.parameters:
                    param_info = temp_obj.parameters[param_key]
                    
                    # Skip calculated parameters (they're computed, not stored)
                    if temp_obj.is_parameter_calculated(param_key):
                        continue
                    
                    # Determine SQL type based on parameter type
                    param_type = param_info.get('type', 'string')
                    if param_type == 'int':
                        sql_type = "INTEGER"
                    elif param_type == 'float':
                        sql_type = "REAL"
                    else:  # string, image, date, text
                        sql_type = "TEXT"
                    
                    # Add column with proper quoting
                    columns.append(f"'{param_key}' {sql_type}")
                    
                    # Add foreign key constraints for ID fields
                    if param_key.endswith('_id') and param_key != 'id':
                        # Determine referenced table based on naming convention
                        if param_key == 'client_id':
                            foreign_keys.append(f"FOREIGN KEY ('{param_key}') REFERENCES 'Clients'(ID)")
                        elif param_key == 'supplier_id':
                            foreign_keys.append(f"FOREIGN KEY ('{param_key}') REFERENCES 'Suppliers'(ID)")
                        elif param_key == 'product_id':
                            foreign_keys.append(f"FOREIGN KEY ('{param_key}') REFERENCES 'Products'(ID)")
                        elif param_key == 'sales_id':
                            foreign_keys.append(f"FOREIGN KEY ('{param_key}') REFERENCES 'Sales'(ID) ON DELETE CASCADE")
                        elif param_key == 'import_id':
                            foreign_keys.append(f"FOREIGN KEY ('{param_key}') REFERENCES 'Imports'(ID) ON DELETE CASCADE")
            
            # Combine columns and foreign keys
            all_constraints = columns + foreign_keys
            constraints_str = ",\n    ".join(all_constraints)
            
            # Create table
            sql = f"""
                CREATE TABLE IF NOT EXISTS '{section_name}' (
                    {constraints_str}
                )
            """
            
            self.cursor.execute(sql)
            self.conn.commit()
            print(f"✓ Created/verified table: {section_name}")
            
        except Exception as e:
            print(f"✗ Error creating table for {section_name}: {e}")
    
    def _create_all_tables(self):
        """Create tables for all registered classes in proper order"""
        # Create tables in order to respect foreign key dependencies
        creation_order = [
            'Products', 'Clients', 'Suppliers',  # Base tables first
            'Sales', 'Imports',                   # Operation tables
            'Sales_Items', 'Import_Items'         # Item tables last
        ]
        
        # Create tables in order if they exist in registered classes
        for section_name in creation_order:
            if section_name in self.registered_classes:
                cls = self.registered_classes[section_name]
                self._create_table_for_class(cls, section_name)
        
        # Create any remaining tables not in the order list
        for section_name, cls in self.registered_classes.items():
            if section_name not in creation_order:
                self._create_table_for_class(cls, section_name)
    
    def save(self, obj):
        """Save any parameter object to database"""
        if not self.cursor:
            print("Database not connected")
            return False
            
        try:
            # Use the object's built-in save method
            if hasattr(obj, 'save_to_database'):
                return obj.save_to_database()
            
            # Fallback: manual save
            return self._manual_save(obj)
            
        except Exception as e:
            print(f"Error saving {obj.section} object: {e}")
            return False
    
    def _manual_save(self, obj):
        """Manual save implementation as fallback"""
        section_name = obj.section
        data = obj.get_value(destination="database")
        
        # Filter out calculated parameters
        filtered_data = {}
        for key, value in data.items():
            if not obj.is_parameter_calculated(key):
                filtered_data[key] = value
        
        if hasattr(obj, 'id') and obj.id and obj.id > 0:
            # Update existing
            return self.update_item(obj.id, filtered_data, section_name)
        else:
            # Insert new and update object's ID
            new_id = self.add_item(filtered_data, section_name)
            if new_id:
                obj.id = new_id
                obj.set_value('id', new_id)
                return True
            return False
    
    def load(self, cls, obj_id):
        """Load and return a parameter object"""
        if not self.cursor:
            print("Database not connected")
            return None
            
        try:
            # Create new instance
            obj = cls(obj_id, self)
            
            # Use the object's built-in load method
            if hasattr(obj, 'load_database_data'):
                if obj.load_database_data():
                    return obj
                else:
                    return None
            
            return None
            
        except Exception as e:
            print(f"Error loading {cls.__name__} with ID {obj_id}: {e}")
            return None
    
    def delete(self, cls_or_obj, obj_id=None):
        """Delete an object and its related items (cascading)"""
        if not self.cursor:
            print("Database not connected")
            return False
        
        try:
            # Begin transaction for cascading deletes
            self.cursor.execute("BEGIN")
            
            if obj_id is None:
                # Object instance passed
                obj = cls_or_obj
                section_name = obj.section
                obj_id = obj.id
            else:
                # Class and ID passed
                cls = cls_or_obj
                temp_obj = cls(0, None)
                section_name = temp_obj.section
            
            # Delete from database (foreign key constraints will handle cascading)
            self.cursor.execute(f"DELETE FROM '{section_name}' WHERE ID = ?", (obj_id,))
            
            # Commit transaction
            self.conn.commit()
            
            return self.cursor.rowcount > 0
            
        except Exception as e:
            # Rollback on error
            self.conn.rollback()
            print(f"Error deleting object: {e}")
            return False
    
    def begin_transaction(self):
        """Begin a database transaction"""
        if self.cursor:
            self.cursor.execute("BEGIN")
    
    def commit_transaction(self):
        """Commit the current transaction"""
        if self.conn:
            self.conn.commit()
    
    def rollback_transaction(self):
        """Rollback the current transaction"""
        if self.conn:
            self.conn.rollback()
    
    def query(self, cls, **filters):
        """Query objects with optional filters"""
        if not self.cursor:
            print("Database not connected")
            return []
        
        try:
            temp_obj = cls(0, None)
            section_name = temp_obj.section
            
            # Build query
            if filters:
                where_clause = " AND ".join([f"'{k}' = ?" for k in filters.keys()])
                sql = f"SELECT * FROM '{section_name}' WHERE {where_clause}"
                params = list(filters.values())
            else:
                sql = f"SELECT * FROM '{section_name}'"
                params = []
            
            # Execute query
            self.cursor.execute(sql, params)
            rows = self.cursor.fetchall()
            
            # Convert to objects
            objects = []
            for row in rows:
                obj_id = row[0]  # ID is always first column
                obj = self.load(cls, obj_id)
                if obj:
                    objects.append(obj)
            
            return objects
            
        except Exception as e:
            print(f"Error querying {cls.__name__}: {e}")
            return []
    
    def get_all(self, cls):
        """Get all objects of a given class"""
        return self.query(cls)
    
    # Updated legacy methods for backward compatibility
    def add_item(self, data, section):
        """Add item to database and return the new ID"""
        if not self.cursor or section not in self.registered_classes:
            return None
        
        try:
            # Get parameters that should be stored
            cls = self.registered_classes[section]
            temp_obj = cls(0, None)
            db_params = temp_obj.get_visible_parameters("database")
            
            # Filter data to only include storable parameters
            filtered_data = {}
            for key in db_params:
                if (key in data and 
                    not temp_obj.is_parameter_calculated(key)):
                    filtered_data[key] = data[key]
            
            if not filtered_data:
                return None
            
            # Build INSERT query
            columns = list(filtered_data.keys())
            placeholders = ['?' for _ in columns]
            columns_str = "', '".join(columns)
            placeholders_str = ", ".join(placeholders)
            
            sql = f"INSERT INTO '{section}' ('{columns_str}') VALUES ({placeholders_str})"
            values = list(filtered_data.values())
            
            self.cursor.execute(sql, values)
            self.conn.commit()
            
            # Return the ID of the inserted record
            return self.cursor.lastrowid
            
        except Exception as e:
            print(f"Error adding item to {section}: {e}")
            return None
    
    def update_item(self, item_id, data, section):
        """Update item in database"""
        if not self.cursor or section not in self.registered_classes:
            return False
        
        try:
            # Get parameters that should be stored
            cls = self.registered_classes[section]
            temp_obj = cls(0, None)
            db_params = temp_obj.get_visible_parameters("database")
            
            # Filter data to only include storable parameters
            filtered_data = {}
            for key in db_params:
                if (key in data and 
                    not temp_obj.is_parameter_calculated(key)):
                    filtered_data[key] = data[key]
            
            if not filtered_data:
                return False
            
            # Build UPDATE query
            set_clauses = [f"'{key}' = ?" for key in filtered_data.keys()]
            set_clause = ", ".join(set_clauses)
            values = list(filtered_data.values())
            values.append(item_id)
            
            sql = f"UPDATE '{section}' SET {set_clause} WHERE ID = ?"
            
            self.cursor.execute(sql, values)
            self.conn.commit()
            return True
            
        except Exception as e:
            print(f"Error updating item in {section}: {e}")
            return False
    
    def get_items(self, section):
        """Get all items from section"""
        if not self.cursor or section not in self.registered_classes:
            return []
        
        try:
            self.cursor.execute(f"SELECT * FROM '{section}'")
            rows = self.cursor.fetchall()
            
            # Get column names
            columns = [description[0] for description in self.cursor.description]
            
            # Convert to list of dictionaries
            return [dict(zip(columns, row)) for row in rows]
            
        except Exception as e:
            print(f"Error getting items from {section}: {e}")
            return []
    
    def delete_item(self, item_id, section):
        """Delete item from section"""
        if not self.cursor or section not in self.registered_classes:
            return False
        
        try:
            self.cursor.execute(f"DELETE FROM '{section}' WHERE ID = ?", (item_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting item from {section}: {e}")
            return False
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None