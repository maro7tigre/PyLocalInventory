import re

def safe_replace(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    for old, new in replacements:
        if old in code:
            code = code.replace(old, new)
        else:
            print(f"Warning: Could not find block in {filepath}")
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

replacements = [
(
"""                if catalog:
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
                        "SELECT COALESCE(SUM(quantity), 0) FROM Sales_Items "
                        "JOIN Sales ON Sales.id = Sales_Items.sale_id "
                        "WHERE product_id = %s AND Sales.state != 'on_hold' AND Sales_Items.sale_id != %s",
                        (product_id, current_sale_id)
                    )
                    total_sold = cursor.fetchone()[0]

                    available = total_imported - total_sold""",
"""                if catalog:
                    for p in catalog.get("products", []):
                        if p.get("id") == product_id:
                            available = p.get("stock", 0)
                            break
                else:
                    # GUI thread must NOT block to query database over RPC.
                    # Skip early warning; let SaveWorker and backend validate stock.
                    continue"""
)
]

safe_replace("ui/dialogs/edit_dialogs/base_operation_dialog.py", replacements)
print("Patched _validate_stock")
