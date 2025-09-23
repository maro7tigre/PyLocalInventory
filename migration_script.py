"""
Database Migration Script
Adds product_id column to Sales_Items table and migrates existing data
"""

import sqlite3
import os
import sys


def migrate_database(db_path):
    """
    Migrate the database to add product_id to Sales_Items
    """
    print(f"Starting migration for database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Enable foreign key support
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Check if Sales_Items table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Sales_Items'")
        if not cursor.fetchone():
            print("Sales_Items table not found. Creating new structure...")
            # Create the table with product_id
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS 'Sales_Items' (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    'sales_id' INTEGER,
                    'product_id' INTEGER,
                    'quantity' INTEGER,
                    'unit_price' REAL,
                    FOREIGN KEY ('sales_id') REFERENCES 'Sales'(ID) ON DELETE CASCADE,
                    FOREIGN KEY ('product_id') REFERENCES 'Products'(ID)
                )
            """)
            conn.commit()
            print("✓ Created Sales_Items table with product_id")
            return True
        
        # Check if product_id column already exists
        cursor.execute("PRAGMA table_info(Sales_Items)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'product_id' in columns:
            print("✓ product_id column already exists in Sales_Items")
            
            # Check if we have product_name column that needs migration
            if 'product_name' in columns:
                print("Found product_name column. Starting migration...")
                
                # Begin transaction
                cursor.execute("BEGIN")
                
                try:
                    # Get all sales items with product_name
                    cursor.execute("SELECT ID, product_name FROM Sales_Items WHERE product_name IS NOT NULL AND product_name != ''")
                    items_to_migrate = cursor.fetchall()
                    
                    migrated_count = 0
                    for item_id, product_name in items_to_migrate:
                        # Find product ID by name
                        cursor.execute("SELECT ID FROM Products WHERE name = ? OR display_name = ? LIMIT 1", (product_name, product_name))
                        product_result = cursor.fetchone()
                        
                        if product_result:
                            product_id = product_result[0]
                            # Update the sales item with product_id
                            cursor.execute("UPDATE Sales_Items SET product_id = ? WHERE ID = ?", (product_id, item_id))
                            migrated_count += 1
                        else:
                            print(f"Warning: Product '{product_name}' not found for sales item ID {item_id}")
                    
                    # Commit the migration
                    conn.commit()
                    print(f"✓ Migrated {migrated_count} sales items to use product_id")
                    
                    # Optionally remove product_name column (commented out for safety)
                    # print("Removing product_name column...")
                    # cursor.execute("ALTER TABLE Sales_Items DROP COLUMN product_name")
                    # conn.commit()
                    # print("✓ Removed product_name column")
                    
                except Exception as e:
                    conn.rollback()
                    print(f"✗ Migration failed: {e}")
                    return False
            
            return True
        
        print("Adding product_id column to Sales_Items...")
        
        # Begin transaction
        cursor.execute("BEGIN")
        
        try:
            # Add product_id column
            cursor.execute("ALTER TABLE Sales_Items ADD COLUMN product_id INTEGER")
            
            # Create foreign key constraint (SQLite doesn't support adding constraints after table creation)
            # We'll need to recreate the table with proper constraints
            print("Recreating table with proper foreign key constraints...")
            
            # Step 1: Create new table with constraints
            cursor.execute("""
                CREATE TABLE Sales_Items_new (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    'sales_id' INTEGER,
                    'product_id' INTEGER,
                    'product_name' TEXT,
                    'quantity' INTEGER,
                    'unit_price' REAL,
                    FOREIGN KEY ('sales_id') REFERENCES 'Sales'(ID) ON DELETE CASCADE,
                    FOREIGN KEY ('product_id') REFERENCES 'Products'(ID)
                )
            """)
            
            # Step 2: Copy data from old table
            cursor.execute("""
                INSERT INTO Sales_Items_new (ID, sales_id, product_name, quantity, unit_price)
                SELECT ID, sales_id, product_name, quantity, unit_price
                FROM Sales_Items
            """)
            
            # Step 3: Try to populate product_id based on product_name
            cursor.execute("SELECT ID, product_name FROM Sales_Items_new WHERE product_name IS NOT NULL AND product_name != ''")
            items_to_update = cursor.fetchall()
            
            migrated_count = 0
            for item_id, product_name in items_to_update:
                # Find product ID by name
                cursor.execute("SELECT ID FROM Products WHERE name = ? OR display_name = ? LIMIT 1", (product_name, product_name))
                product_result = cursor.fetchone()
                
                if product_result:
                    product_id = product_result[0]
                    cursor.execute("UPDATE Sales_Items_new SET product_id = ? WHERE ID = ?", (product_id, item_id))
                    migrated_count += 1
                else:
                    print(f"Warning: Product '{product_name}' not found for sales item ID {item_id}")
            
            # Step 4: Drop old table and rename new one
            cursor.execute("DROP TABLE Sales_Items")
            cursor.execute("ALTER TABLE Sales_Items_new RENAME TO Sales_Items")
            
            # Commit the transaction
            conn.commit()
            print(f"✓ Added product_id column and migrated {migrated_count} items")
            
        except Exception as e:
            conn.rollback()
            print(f"✗ Failed to add product_id column: {e}")
            return False
        
        # Add display_name column to Products, Clients, Suppliers if missing
        tables_to_check = ['Products', 'Clients', 'Suppliers']
        
        for table_name in tables_to_check:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'display_name' not in columns:
                print(f"Adding display_name column to {table_name}...")
                try:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN display_name TEXT")
                    
                    # Copy name to display_name for existing records
                    cursor.execute(f"UPDATE {table_name} SET display_name = name WHERE display_name IS NULL")
                    
                    conn.commit()
                    print(f"✓ Added display_name column to {table_name}")
                except Exception as e:
                    print(f"✗ Failed to add display_name to {table_name}: {e}")
        
        # Close connection
        conn.close()
        print("✓ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False


def main():
    """Main migration function"""
    
    # Default database path (adjust as needed)
    default_db_path = r"profiles\2025\2025.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = input(f"Enter database path (default: {default_db_path}): ").strip()
        if not db_path:
            db_path = default_db_path
    
    print("=" * 60)
    print("Database Migration Script")
    print("This will add product_id to Sales_Items and display_name columns")
    print("=" * 60)
    
    confirm = input(f"Migrate database '{db_path}'? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Migration cancelled.")
        return
    
    # Create backup
    backup_path = db_path + ".backup"
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✓ Created backup: {backup_path}")
    except Exception as e:
        print(f"Warning: Could not create backup: {e}")
        proceed = input("Continue without backup? (y/N): ").strip().lower()
        if proceed != 'y':
            print("Migration cancelled.")
            return
    
    # Run migration
    success = migrate_database(db_path)
    
    if success:
        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("You can now use the updated PyLocalInventory application.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("Migration failed!")
        print(f"You can restore from backup: {backup_path}")
        print("=" * 60)


if __name__ == "__main__":
    main()