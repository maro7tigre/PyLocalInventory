with open("tests/test_recent_changes_full.py", "r", encoding="utf-8") as f:
    lines = f.read()

lines = lines.replace(
"""        if dialog.load_worker:
            dialog.load_worker.process()
        dialog._on_load_finished()
        if hasattr(dialog, 'load_thread') and dialog.load_thread:
            dialog.load_thread.quit()
            dialog.load_thread.wait()""",
"""        if dialog.load_worker:
            dialog.load_worker.process()
        
        lt = dialog.load_thread
        dialog._on_load_finished()
        if lt:
            lt.quit()
            lt.wait()"""
)

lines = lines.replace(
"""        # Process worker
        dialog.save_worker.process()
        dialog._on_save_finished({"sale_id": 1, "expected": 1, "saved": 1}, "updated")
        if hasattr(dialog, 'save_thread') and dialog.save_thread:
            dialog.save_thread.quit()
            dialog.save_thread.wait()""",
"""        # Process worker
        dialog.save_worker.process()
        
        st = dialog.save_thread
        dialog._on_save_finished({"sale_id": 1, "expected": 1, "saved": 1}, "updated")
        if st:
            st.quit()
            st.wait()"""
)

lines = lines.replace(
"""        dialog._on_load_error("Load error!")
        mock_warn.assert_called()
        if hasattr(dialog, 'load_thread') and dialog.load_thread:
            dialog.load_thread.quit()
            dialog.load_thread.wait()""",
"""        lt = dialog.load_thread
        dialog._on_load_error("Load error!")
        mock_warn.assert_called()
        if lt:
            lt.quit()
            lt.wait()"""
)

with open("tests/test_recent_changes_full.py", "w", encoding="utf-8") as f:
    f.write(lines)
