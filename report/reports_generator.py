"""
Reports Generator - generates various reports from database data
"""
from datetime import datetime


class ReportsGenerator:
    def __init__(self, database):
        self.database = database
    
    def generate_client_report(self, client_id):
        """Generate report for a specific client showing imports and sales"""
        if not self.database or not self.database.cursor:
            return [], [], ""
        
        try:
            # Get client info
            self.database.cursor.execute("SELECT * FROM Clients WHERE ID = ?", (client_id,))
            client_data = self.database.cursor.fetchone()
            if not client_data:
                return [], [], "Client not found"
            
            client_name = client_data[1]  # Assuming name is in column 1
            
            # Get sales for this client
            self.database.cursor.execute("""
                SELECT s.date, p.name, s.quantity, s.unit_price, s.total_price 
                FROM Sales s 
                JOIN Products p ON s.product_id = p.ID 
                WHERE s.client_id = ?
                ORDER BY s.date DESC
            """, (client_id,))
            
            sales_data = self.database.cursor.fetchall()
            headers = ["Date", "Product", "Quantity", "Unit Price", "Total Price"]
            
            # Calculate summary
            total_sales = sum(row[4] for row in sales_data) if sales_data else 0
            total_items = sum(row[2] for row in sales_data) if sales_data else 0
            
            summary = f"""Client: {client_name}
Total Sales: {len(sales_data)} transactions
Total Items Sold: {total_items}
Total Revenue: €{total_sales:.2f}
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            return headers, sales_data, summary
            
        except Exception as e:
            print(f"Error generating client report: {e}")
            return [], [], "Error generating report"
    
    def generate_product_report(self, product_id):
        """Generate report for a specific product showing imports and sales"""
        if not self.database or not self.database.cursor:
            return [], [], ""
        
        try:
            # Get product info
            self.database.cursor.execute("SELECT * FROM Products WHERE ID = ?", (product_id,))
            product_data = self.database.cursor.fetchone()
            if not product_data:
                return [], [], "Product not found"
            
            product_name = product_data[1]  # Assuming name is in column 1
            
            # Get imports for this product
            self.database.cursor.execute("""
                SELECT 'Import' as type, i.date, s.name, i.quantity, i.unit_price, i.total_price
                FROM Imports i 
                JOIN Suppliers s ON i.supplier_id = s.ID 
                WHERE i.product_id = ?
                UNION ALL
                SELECT 'Sale' as type, sa.date, c.name, sa.quantity, sa.unit_price, sa.total_price
                FROM Sales sa
                JOIN Clients c ON sa.client_id = c.ID 
                WHERE sa.product_id = ?
                ORDER BY date DESC
            """, (product_id, product_id))
            
            transactions = self.database.cursor.fetchall()
            headers = ["Type", "Date", "Partner", "Quantity", "Unit Price", "Total Price"]
            
            # Calculate summary
            imports = [t for t in transactions if t[0] == 'Import']
            sales = [t for t in transactions if t[0] == 'Sale']
            
            total_imported = sum(t[3] for t in imports)
            total_sold = sum(t[3] for t in sales)
            current_stock = total_imported - total_sold
            
            summary = f"""Product: {product_name}
Total Imported: {total_imported}
Total Sold: {total_sold}
Current Stock: {current_stock}
Total Transactions: {len(transactions)}
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            return headers, transactions, summary
            
        except Exception as e:
            print(f"Error generating product report: {e}")
            return [], [], "Error generating report"
    
    def generate_supplier_report(self, supplier_id):
        """Generate report for a specific supplier showing imports"""
        if not self.database or not self.database.cursor:
            return [], [], ""
        
        try:
            # Get supplier info
            self.database.cursor.execute("SELECT * FROM Suppliers WHERE ID = ?", (supplier_id,))
            supplier_data = self.database.cursor.fetchone()
            if not supplier_data:
                return [], [], "Supplier not found"
            
            supplier_name = supplier_data[1]  # Assuming name is in column 1
            
            # Get imports from this supplier
            self.database.cursor.execute("""
                SELECT i.date, p.name, i.quantity, i.unit_price, i.total_price 
                FROM Imports i 
                JOIN Products p ON i.product_id = p.ID 
                WHERE i.supplier_id = ?
                ORDER BY i.date DESC
            """, (supplier_id,))
            
            imports_data = self.database.cursor.fetchall()
            headers = ["Date", "Product", "Quantity", "Unit Price", "Total Price"]
            
            # Calculate summary
            total_cost = sum(row[4] for row in imports_data) if imports_data else 0
            total_items = sum(row[2] for row in imports_data) if imports_data else 0
            
            summary = f"""Supplier: {supplier_name}
Total Imports: {len(imports_data)} transactions
Total Items Imported: {total_items}
Total Cost: €{total_cost:.2f}
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            return headers, imports_data, summary
            
        except Exception as e:
            print(f"Error generating supplier report: {e}")
            return [], [], "Error generating report"
    
    def generate_inventory_summary(self):
        """Generate overall inventory summary"""
        if not self.database or not self.database.cursor:
            return [], [], ""
        
        try:
            # Get all products with their calculated quantities
            self.database.cursor.execute("SELECT ID, name, unit_price, sale_price FROM Products")
            products = self.database.cursor.fetchall()
            
            inventory_data = []
            total_value = 0
            
            for product in products:
                product_id, name, unit_price, sale_price = product
                
                # Calculate stock for each product
                self.database.cursor.execute("SELECT SUM(quantity) FROM Imports WHERE product_id = ?", (product_id,))
                imports_result = self.database.cursor.fetchone()
                total_imports = imports_result[0] if imports_result[0] else 0
                
                self.database.cursor.execute("SELECT SUM(quantity) FROM Sales WHERE product_id = ?", (product_id,))
                sales_result = self.database.cursor.fetchone()
                total_sales = sales_result[0] if sales_result[0] else 0
                
                current_stock = total_imports - total_sales
                stock_value = current_stock * unit_price
                total_value += stock_value
                
                inventory_data.append([name, current_stock, f"€{unit_price:.2f}", f"€{sale_price:.2f}", f"€{stock_value:.2f}"])
            
            headers = ["Product", "Stock", "Unit Price", "Sale Price", "Stock Value"]
            
            summary = f"""Inventory Summary
Total Products: {len(products)}
Total Stock Value: €{total_value:.2f}
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            return headers, inventory_data, summary
            
        except Exception as e:
            print(f"Error generating inventory summary: {e}")
            return [], [], "Error generating report"