import pywinauto
from pywinauto.application import Application
import time

def test_app():
    # start app
    print("Starting packaged app...")
    app = Application(backend="uia").start(r"dist\PyLocalInventory\PyLocalInventory.exe")
    
    # wait for main window
    print("Waiting for main window...")
    main_dlg = app.window(title_re=".*PyLocalInventory.*")
    main_dlg.wait("ready", timeout=20)
    
    print("Clicking Sales Tab...")
    try:
        sales_tab = main_dlg.child_window(title="Sales", control_type="TabItem")
        sales_tab.click_input()
        time.sleep(1)
    except:
        print("Could not find Sales tab.")
        
    print("Clicking Add Sale...")
    try:
        add_btn = main_dlg.child_window(title="Add Sale", control_type="Button")
        add_btn.click_input()
    except:
        print("Could not find Add Sale button.")
    
    # wait for dialog
    print("Waiting for sale dialog...")
    sale_dlg = app.window(title_re=".*Sale.*")
    sale_dlg.wait("ready", timeout=10)
    
    print("Dialog title:", sale_dlg.window_text())
    if "NoneType" in sale_dlg.window_text() or "Error" in sale_dlg.window_text():
        print("RESULT: NoneType Error")
    else:
        print("RESULT: Add Sale Opened successfully")
        
    # wait for loading to finish
    time.sleep(3)
    
    print("Clicking Save...")
    try:
        save_btn = sale_dlg.child_window(title="Save", control_type="Button")
        save_btn.click_input()
        time.sleep(3)
    except:
        print("Could not find Save button.")
    
    # dialog should be closed or show an error
    # but the app should still be running!
    time.sleep(1)
    if main_dlg.exists():
        print("RESULT: Main application remained open!")
    else:
        print("RESULT: Application crashed!")

    # close main app
    print("Closing app...")
    try:
        main_dlg.close()
    except:
        pass

if __name__ == "__main__":
    test_app()
