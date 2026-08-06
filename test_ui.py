import sys
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from ui.main_window import MainWindow

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    results = {}
    
    def step1():
        print("Step 1: Switching to Sales tab...")
        try:
            # Sales is usually tab index 1 (after Clients)
            window.tabs.setCurrentIndex(1)
        except:
            pass
        add_btn = None
        sales_tab = window.tabs.currentWidget()
        if hasattr(sales_tab, 'add_btn'):
            add_btn = sales_tab.add_btn
        if add_btn:
            print("Clicking Add Sale...")
            add_btn.click()
            QTimer.singleShot(3000, step2)
        else:
            print("Could not find Add Sale button")
            QTimer.singleShot(1000, app.quit)

    def step2():
        print("Step 2: Checking Sale dialog...")
        top_widgets = app.topLevelWidgets()
        dlg = None
        for w in top_widgets:
            if "Sale" in w.windowTitle() or "Loading" in w.windowTitle() or "Error" in w.windowTitle():
                dlg = w
                break
        if dlg:
            print(f"Found dialog: {dlg.windowTitle()}")
            results['Add Sale opened'] = True
            if "NoneType" in dlg.windowTitle() or "Error" in dlg.windowTitle():
                results['NoneType Error'] = True
            
            if hasattr(dlg, 'save_btn'):
                print("Clicking Save...")
                # Put some data to save
                if hasattr(dlg, 'items_table'):
                    pass # maybe add a row if needed, but save should work even empty or show validation
                dlg.save_btn.click()
                QTimer.singleShot(3000, step3)
            else:
                print("No save button")
                QTimer.singleShot(1000, app.quit)
        else:
            print("No dialog found")
            QTimer.singleShot(1000, app.quit)
            
    def step3():
        print("Step 3: Checking if main window is still open...")
        results['Main open'] = window.isVisible()
        print("Main window visible:", window.isVisible())
        
        top_widgets = app.topLevelWidgets()
        for w in top_widgets:
            if "Sale" in w.windowTitle():
                results['Dialog still open'] = w.isVisible()
        
        app.quit()
        
    QTimer.singleShot(1000, step1)
    
    QTimer.singleShot(15000, app.quit) # timeout
    app.exec()
    print("RESULTS:", results)

if __name__ == "__main__":
    run_test()
