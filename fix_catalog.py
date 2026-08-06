import re

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

old_exists = """    def _catalog_entity_exists(self, item_type, name):
        table = "Products" if item_type == "product" else "Services"
        target = self._normalize_name(name)
        self.database.cursor.execute(
            f"SELECT name FROM {table} WHERE name IS NOT NULL"
        )
        return any(
            self._normalize_name(row[0]) == target
            for row in self.database.cursor.fetchall()
        )"""

new_exists = """    def _catalog_entity_exists(self, item_type, name):
        target = self._normalize_name(name)
        catalog = getattr(self.database, 'sale_catalog', None)
        if catalog:
            entities = catalog.get(item_type + "s", [])
            for e in entities:
                if self._normalize_name(e.get("name", "")) == target:
                    return True
            return False
            
        # fallback to db
        table = "Products" if item_type == "product" else "Services"
        self.database.cursor.execute(
            f"SELECT name FROM {table} WHERE name IS NOT NULL"
        )
        return any(
            self._normalize_name(row[0]) == target
            for row in self.database.cursor.fetchall()
        )"""

content = content.replace(old_exists, new_exists)

old_validate = """    def _validate_stock(self, items_objects):
        \"\"\"Return a list of error strings for any sale item that exceeds available stock.

        Excludes the current sale's own existing items from the deduction so that editing
        a sale and changing quantities is checked correctly (not double-counted).
        \"\"\"
        errors = []
        current_sale_id = self.operation_id or 0
        cursor = self.database.cursor
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue

                cursor.execute(
                    "SELECT COALESCE(SUM(quantity), 0) FROM Import_Items WHERE product_id = %s",
                    (product_id,)
                )
                total_imported = cursor.fetchone()[0]

                cursor.execute(
                    \"\"\"
                    SELECT COALESCE(SUM(si.quantity), 0)
                    FROM Sale_Items si
                    JOIN Sales s ON si.sale_id = s.id
                    WHERE si.product_id = %s
                      AND s.state != 'on_hold'
                      AND s.id != %s
                    \"\"\",
                    (product_id, current_sale_id)
                )
                total_sold = cursor.fetchone()[0]

                available = total_imported - total_sold
                if new_qty > float(available):
                    errors.append(f"{product_name} (Requested: {new_qty}, Available: {available})")
            except Exception as e:
                print(f"Stock check error: {e}")
        return errors"""

new_validate = """    def _validate_stock(self, items_objects):
        \"\"\"Return a list of error strings for any sale item that exceeds available stock.\"\"\"
        errors = []
        current_sale_id = self.operation_id or 0
        catalog = getattr(self.database, 'sale_catalog', None)
        
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue
                
                available = 0
                if catalog:
                    for p in catalog.get("products", []):
                        if p.get("id") == product_id:
                            available = p.get("stock", 0)
                            break
                else:
                    cursor = self.database.cursor
                    cursor.execute(
                        "SELECT COALESCE(SUM(quantity), 0) FROM Import_Items WHERE product_id = %s",
                        (product_id,)
                    )
                    total_imported = cursor.fetchone()[0]

                    cursor.execute(
                        \"\"\"
                        SELECT COALESCE(SUM(si.quantity), 0)
                        FROM Sale_Items si
                        JOIN Sales s ON si.sale_id = s.id
                        WHERE si.product_id = %s
                          AND s.state != 'on_hold'
                          AND s.id != %s
                        \"\"\",
                        (product_id, current_sale_id)
                    )
                    total_sold = cursor.fetchone()[0]
                    available = total_imported - total_sold
                    
                if new_qty > float(available):
                    errors.append(f"{product_name} (Requested: {new_qty}, Available: {available})")
            except Exception as e:
                print(f"Stock check error: {e}")
        return errors"""

content = content.replace(old_validate, new_validate)

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
