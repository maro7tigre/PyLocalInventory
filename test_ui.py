import sys
import time
from PySide6.QtWidgets import QApplication, QTableView
from PySide6.QtCore import QTimer, Qt
from ui.main_window import MainWindow

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    results = {}
    
    def step_open_sales_tab():
        print("\n--- Testing Sales ---")
        window.tab_widget.setCurrentIndex(6) # Try switching to Sales (index 6 usually based on my previous knowledge, but let's just find it by name)
        for i in range(window.tab_widget.count()):
            if "Sales" in window.tab_widget.tabText(i):
                window.tab_widget.setCurrentIndex(i)
                break
        QTimer.singleShot(1500, step_open_existing_sale)

    def step_open_existing_sale():
        print("B. Open EXISTING Sale")
        sales_tab = window.tab_widget.currentWidget()
        # Find the table view
        table_view = sales_tab.findChild(QTableView)
        if table_view and table_view.model() and table_view.model().rowCount() > 0:
            print("Found existing sales. Double clicking first row...")
            index = table_view.model().index(0, 0)
            sales_tab.table_view.doubleClicked.emit(index)
            QTimer.singleShot(3000, step_check_existing_sale)
        else:
            print("No existing sales to open.")
            results['Existing Sale Result'] = "No existing sales found"
            QTimer.singleShot(1000, step_open_add_sale)

    def step_check_existing_sale():
        dlg = None
        for w in app.topLevelWidgets():
            if "Sale" in w.windowTitle() and "Loading" not in w.windowTitle():
                dlg = w
                break
        if dlg:
            results['Existing Sale Result'] = "Passed (Opened)"
            # check rows
            rows = dlg.items_table.table.rowCount()
            print(f"Existing sale has {rows} item rows.")
            if rows > 0:
                results['Existing Sale Result'] += f", {rows} rows loaded"
            else:
                results['Existing Sale Result'] += ", 0 rows loaded"
                
            print("F. Editing and saving existing sale...")
            dlg.save_btn.click()
            QTimer.singleShot(3000, step_open_add_sale)
        else:
            results['Existing Sale Result'] = "Failed (Dialog not found or crashed)"
            QTimer.singleShot(1000, step_open_add_sale)

    def step_open_add_sale():
        print("C. Open Add Sale")
        sales_tab = window.tab_widget.currentWidget()
        sales_tab.add_btn.click()
        QTimer.singleShot(3000, step_check_add_sale)

    def step_check_add_sale():
        dlg = None
        for w in app.topLevelWidgets():
            if "Sale" in w.windowTitle() and "Loading" not in w.windowTitle() and w.isVisible():
                dlg = w
                break
        if dlg:
            results['New Sale Result'] = "Passed (Opened)"
            dlg.reject() # close without saving
            QTimer.singleShot(1000, step_open_imports_tab)
        else:
            results['New Sale Result'] = "Failed"
            QTimer.singleShot(1000, step_open_imports_tab)

    def step_open_imports_tab():
        print("\n--- Testing Imports ---")
        for i in range(window.tab_widget.count()):
            if "Imports" in window.tab_widget.tabText(i):
                window.tab_widget.setCurrentIndex(i)
                break
        QTimer.singleShot(1500, step_open_existing_import)

    def step_open_existing_import():
        print("D. Open EXISTING Import")
        imports_tab = window.tab_widget.currentWidget()
        table_view = imports_tab.findChild(QTableView)
        if table_view and table_view.model() and table_view.model().rowCount() > 0:
            print("Found existing imports. Double clicking first row...")
            index = table_view.model().index(0, 0)
            imports_tab.table_view.doubleClicked.emit(index)
            QTimer.singleShot(3000, step_check_existing_import)
        else:
            print("No existing imports to open.")
            results['Existing Import Result'] = "No existing imports found"
            QTimer.singleShot(1000, step_open_add_import)

    def step_check_existing_import():
        dlg = None
        for w in app.topLevelWidgets():
            if "Import" in w.windowTitle() and "Loading" not in w.windowTitle() and w.isVisible():
                dlg = w
                break
        if dlg:
            results['Existing Import Result'] = "Passed (Opened)"
            rows = dlg.items_table.table.rowCount()
            print(f"Existing import has {rows} item rows.")
            if rows > 0:
                results['Existing Import Result'] += f", {rows} rows loaded"
            else:
                results['Existing Import Result'] += ", 0 rows loaded"
            dlg.reject()
            QTimer.singleShot(1000, step_open_add_import)
        else:
            results['Existing Import Result'] = "Failed"
            QTimer.singleShot(1000, step_open_add_import)

    def step_open_add_import():
        print("E. Open Add Import")
        imports_tab = window.tab_widget.currentWidget()
        imports_tab.add_btn.click()
        QTimer.singleShot(3000, step_check_add_import)

    def step_check_add_import():
        dlg = None
        for w in app.topLevelWidgets():
            if "Import" in w.windowTitle() and "Loading" not in w.windowTitle() and w.isVisible():
                dlg = w
                break
        if dlg:
            results['New Import Result'] = "Passed (Opened)"
            dlg.reject()
        else:
            results['New Import Result'] = "Failed"
            
        print("\nAll tests completed.")
        app.quit()
        
    QTimer.singleShot(1500, step_open_sales_tab)
    QTimer.singleShot(30000, app.quit) # safety timeout
    
    app.exec()
    print("\nRESULTS:")
    for k, v in results.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    run_test()
