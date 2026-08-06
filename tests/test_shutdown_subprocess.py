import os
import sys
import subprocess
import unittest
from pathlib import Path

class TestShutdownSubprocess(unittest.TestCase):
    def test_shutdown_with_active_thread(self):
        """Verify the application can shutdown cleanly without native crashes even if threads are active."""
        
        # Script to run in the subprocess
        script_code = """
import sys
import os
import time
import threading

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Offscreen QPA to avoid GUI popups during test
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QWidget
from ui.main_window import MainWindow

def run_test():
    app = QApplication(sys.argv)
    
    # Initialize MainWindow (this will start threads)
    window = MainWindow()
    
    # Force creation of tab_widget
    window.setup_main_tabs()
    
    # Inject a dummy thread that will timeout
    class DummyTab(QWidget):
        def _wait_for_refresh_thread(self):
            print("MOCK CALLED: _wait_for_refresh_thread", file=sys.stderr)
            # Simulate a timeout by returning False
            return False
            
    # Add a mock tab to tab_widget
    if getattr(window, 'tab_widget', None):
        mock_widget = DummyTab()
        window.tab_widget.addTab(mock_widget, "Mock")
        
    print(f"Tabs count: {window.tab_widget.count()}", file=sys.stderr)

    # Try to close the window
    # If a thread times out, closeEvent will call event.ignore() and shutting_down is False
    window.close()
    
    assert window._shutting_down == False, "Shutdown should be aborted on thread timeout"
    
    # Ensure we don't crash natively
    sys.exit(0)

if __name__ == '__main__':
    run_test()
"""
        
        test_script_path = Path("tests/temp_shutdown_test.py")
        try:
            test_script_path.write_text(script_code, encoding="utf-8")
            
            # Run the script in a subprocess
            result = subprocess.run(
                [sys.executable, str(test_script_path)],
                capture_output=True,
                text=True,
                timeout=15,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
            )
            
            # Check that it exited cleanly (code 0)
            self.assertEqual(
                result.returncode, 
                0, 
                f"Subprocess crashed with code {result.returncode}.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
            
        finally:
            if test_script_path.exists():
                test_script_path.unlink()

if __name__ == '__main__':
    unittest.main()
