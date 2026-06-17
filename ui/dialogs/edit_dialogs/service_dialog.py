"""
Service Dialog - Edit dialog for services
"""
from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.service_class import ServiceClass
from PySide6.QtWidgets import QMessageBox


class ServiceEditDialog(BaseEditDialog):
    """Dialog for creating or editing services."""

    def __init__(self, service_id=None, database=None, parent=None):
        self.service_id = service_id
        self.database = database

        if service_id:
            self.service = ServiceClass(service_id, database)
            self.service.load_database_data()
            window_title = f"Edit Service - {self.service.get_value('name') or service_id}"
        else:
            self.service = ServiceClass(0, database)
            window_title = "New Service"

        ui_config = {
            'description': {
                'multiline': True
            }
        }

        super().__init__(self.service, ui_config, parent)
        self.setWindowTitle(window_title)

    def validate_data(self):
        errors = super().validate_data()

        service_code = self.service.get_value('service_code')
        if service_code and not self.service.validate_service_code_uniqueness(service_code):
            errors.append(f"Service code '{service_code}' already exists")

        return errors

    def save_changes(self):
        errors = self.validate_data()
        critical_errors = [e for e in errors if not e.lower().startswith('warning')]
        warnings = [e for e in errors if e.lower().startswith('warning')]

        if critical_errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(critical_errors))
            return

        if warnings:
            reply = QMessageBox.question(
                self, "Warning",
                "\n".join(warnings) + "\n\nDo you want to continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        try:
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.service.set_value(param_key, value)

            if not self.service.save_to_database():
                QMessageBox.critical(self, "Error", "Failed to save service to database")
                return

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save service: {str(e)}")

    def get_service_data(self):
        return self.service
