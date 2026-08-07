with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

out = []
in_finished = False
in_error = False

for line in lines:
    if line.startswith("    def _on_save_finished("):
        in_finished = True
        out.append(line)
        continue
    elif line.startswith("    def _on_save_error("):
        in_error = True
        out.append(line)
        continue
    elif line.startswith("    def "):
        in_finished = False
        in_error = False
        out.append(line)
        continue

    if in_finished or in_error:
        if line.strip() in ("self.save_worker = None", "self.save_thread = None", "# Thread cleanup is handled safely by QThread.finished -> deleteLater"):
            out.append(line)
        elif line.strip() == "self._saving = False":
            out.append("        try:\n")
            out.append("    " + line)
        else:
            if line.strip() != "":
                out.append("    " + line)
            else:
                out.append(line)
            
            # check if we reached the end of the method body
            if line.strip() == "self._refresh_related_tabs(\"Sales\", \"Products\", \"Clients\")":
                out.append("        except RuntimeError:\n")
                out.append("            pass\n")
            elif in_error and "QMessageBox.critical" in line:
                out.append("        except RuntimeError:\n")
                out.append("            pass\n")
    else:
        out.append(line)

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.writelines(out)
