"""
Charge Edit Dialog - For creating/editing operating expenses
"""
from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.charge_class import ChargeClass
from PySide6.QtWidgets import QMessageBox, QLabel
from ui.widgets.parameters_widgets import ParameterWidgetFactory, ComboWidget


class ChargeEditDialog(BaseEditDialog):
    """Charge-specific edit dialog"""
    
    def __init__(self, charge_id=None, database=None, parent=None):
        self.charge_id = charge_id
        self.database = database
        
        if charge_id:
            self.charge = ChargeClass(charge_id, database)
            self.charge.load_database_data()
            window_title = f"Edit Charge - {self.charge.get_value('description') or 'Unnamed'}"
        else:
            self.charge = ChargeClass(0, database)
            window_title = "New Charge"
        
        # Define charge-specific UI configuration
        ui_config = {
            'expense_date': {
                'type': 'date',
                'required': True,
            },
            'category_id': {
                'type': 'combo',
                'required': True,
            },
            'description': {
                'multiline': True,
            },
            'amount': {
                'type': 'decimal',
                'precision': 2,
                'min': 0,
                'allow_blank': True,
                'unit': 'MAD',
                'required': True,
            },
            'payment_method': {
                'type': 'combo',
                'options': [
                    ('Cash', 'Cash'),
                    ('Bank Transfer', 'Bank'),
                    ('Check', 'Check'),
                    ('Card', 'Card'),
                    ('Other', 'Other'),
                ],
            },
            'reference': {
                'type': 'text',
            },
            'notes': {
                'multiline': True,
            },
            'recurring_template_id': {
                'type': 'combo',
            },
        }
        
        super().__init__(self.charge, ui_config, parent)
        
        self.setWindowTitle(window_title)
        self.setMinimumSize(620, 620)
        self.resize(680, 760)
        self._saving = False
        
        # Populate combos after UI is set up
        self._populate_categories()
        self._populate_recurring_templates()

        amount_widget = self.parameter_widgets.get('amount')
        if amount_widget is not None and hasattr(amount_widget, 'spinbox'):
            amount_widget.spinbox.setMinimumWidth(220)
        for key in ('category_id', 'payment_method', 'recurring_template_id'):
            widget = self.parameter_widgets.get(key)
            if isinstance(widget, ComboWidget):
                widget.combo.setMinimumWidth(320)

        if charge_id:
            from ui.widgets.attachments_widget import AttachmentPanel
            attachments_label = QLabel("Attachments")
            attachments_label.setStyleSheet("font-size: 15px; font-weight: bold;")
            self.layout().insertWidget(self.layout().count() - 1, attachments_label)
            self.attachments_panel = AttachmentPanel(
                self.database, 'charge', int(charge_id), self
            )
            self.layout().insertWidget(
                self.layout().count() - 1, self.attachments_panel
            )
        else:
            self.attachments_panel = None
            attachments_hint = QLabel(
                "Attachments can be added after the charge is saved."
            )
            attachments_hint.setStyleSheet("color: #aaaaaa; font-style: italic;")
            self.layout().insertWidget(self.layout().count() - 1, attachments_hint)
        
        # Set default date to today for new charges
        if not charge_id:
            self._set_default_date()
    
    def _set_default_date(self):
        """Set default expense date to today"""
        from PySide6.QtCore import QDate
        if 'expense_date' in self.parameter_widgets:
            widget = self.parameter_widgets['expense_date']
            if hasattr(widget, 'date_edit'):
                widget.date_edit.setDate(QDate.currentDate())
    
    def _populate_categories(self):
        """Populate category combo with active categories from database"""
        if 'category_id' not in self.parameter_widgets:
            return
        
        widget = self.parameter_widgets['category_id']
        if not isinstance(widget, ComboWidget):
            return
        
        try:
            categories = self.database.get_charge_categories()
            current_cat_id = self.charge.get_value('category_id') if self.charge_id else None
            options = []
            for cat in categories:
                if cat["active"] or cat["id"] == current_cat_id:
                    label = cat["name"] + (" (Inactive)" if not cat["active"] else "")
                    options.append((label, cat["id"]))
            widget.set_options(options)
            
            # If editing, set current value
            if self.charge_id:
                current_cat_id = self.charge.get_value('category_id')
                if current_cat_id:
                    widget.setValue(current_cat_id)
        except Exception as e:
            widget.setEnabled(False)
            self.save_btn.setEnabled(False)
            QMessageBox.critical(self, "Categories", f"Could not load charge categories:\n{e}")
    
    def _populate_recurring_templates(self):
        """Populate recurring templates combo"""
        if 'recurring_template_id' not in self.parameter_widgets:
            return
        
        widget = self.parameter_widgets['recurring_template_id']
        if not isinstance(widget, ComboWidget):
            return
        
        try:
            templates = self.database.get_recurring_templates()
            # Only show enabled templates
            options = [("No recurring template", None)]
            for tpl in templates:
                current_tpl_id = self.charge.get_value('recurring_template_id') if self.charge_id else None
                if tpl.get("enabled", False) or tpl["id"] == current_tpl_id:
                    amount = float(tpl.get('default_amount') or 0)
                    label = f"{tpl['name']} - {amount:,.2f} MAD"
                    if not tpl.get("enabled", False):
                        label += " (Disabled)"
                    options.append((label, tpl["id"]))
            widget.set_options(options)
            
            # If editing, set current value
            if self.charge_id:
                current_tpl_id = self.charge.get_value('recurring_template_id')
                if current_tpl_id:
                    widget.setValue(current_tpl_id)
        except Exception as e:
            widget.set_options([("No recurring template", None)])
            QMessageBox.warning(self, "Recurring Templates", f"Could not load templates:\n{e}")
    
    def validate_data(self):
        """Charge-specific validation"""
        errors = super().validate_data()
        
        # Get current values from widgets
        amount = None
        expense_date = None
        category_id = None
        
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'amount':
                amount = self.get_widget_value(widget)
            elif param_key == 'expense_date':
                expense_date = self.get_widget_value(widget)
            elif param_key == 'category_id':
                category_id = self.get_widget_value(widget)
        
        if amount is not None and amount <= 0:
            errors.append("Amount must be greater than zero")
        
        if not expense_date:
            errors.append("Expense date is required")
        
        if not category_id:
            errors.append("Category is required")
        
        return errors
    
    def save_changes(self):
        """Save charge changes"""
        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        try:
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
            
            # Update charge object with form data
            form_values = {}
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                form_values[param_key] = value
            
            for param_key, value in form_values.items():
                self.charge.set_value(param_key, value)
            
            # Save to database
            charge_data = self.charge.get_value(destination="database")
            if not self.charge_id:
                result = self.database.save_charge(charge_data)
                success = bool(result and result.get("id"))
                if success:
                    self.charge.id = int(result["id"])
                    self.charge.parameters["id"]["value"] = self.charge.id
            else:
                charge_data = self.charge.get_value(destination="database")
                result = self.database.save_charge(charge_data, self.charge_id)
                success = bool(result and result.get("transaction") == "committed")
            
            if success:
                self.accept()
            else:
                QMessageBox.critical(self, "Error", "Failed to save charge to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save charge: {str(e)}")
        finally:
            if self.result() != QMessageBox.Accepted:
                self._saving = False
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        return ParameterWidgetFactory.get_widget_value(widget)
