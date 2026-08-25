"""
Charge Class - Operating Expenses
"""
from classes.base_class import BaseClass


class ChargeClass(BaseClass):
    """Charge / Operating Expense management"""
    
    def __init__(self, id, database):
        super().__init__(id, database)
        self.section = "Charges"
        
        # Define parameters for charges
        self.parameters = {
            "id": {
                "value": 0,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "expense_date": {
                "value": "",
                "display_name": {"en": "Expense Date", "fr": "Date de dépense", "es": "Fecha de gasto"},
                "required": True,
                "default": "",
                "options": [],
                "type": "date",
            },
            "category_id": {
                "value": 0,
                "display_name": {"en": "Category", "fr": "Catégorie", "es": "Categoría"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "category_name": {
                "value": "",
                "display_name": {"en": "Category", "fr": "Catégorie", "es": "Categoría"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "description": {
                "value": "",
                "display_name": {"en": "Description", "fr": "Description", "es": "Descripción"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
                "multiline": True,
            },
            "amount": {
                "value": 0,
                "display_name": {"en": "Amount", "fr": "Montant", "es": "Monto"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "decimal",
                "precision": 2,
                "min": 0,
            },
            "payment_method": {
                "value": "Cash",
                "display_name": {"en": "Payment Method", "fr": "Mode de paiement", "es": "Método de pago"},
                "required": False,
                "default": "Cash",
                "options": ["Cash", "Bank", "Check", "Card", "Other"],
                "type": "string",
            },
            "reference": {
                "value": "",
                "display_name": {"en": "Reference", "fr": "Référence", "es": "Referencia"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "notes": {
                "value": "",
                "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
                "multiline": True,
            },
            "recurring_template_id": {
                "value": None,
                "display_name": {"en": "Recurring Template", "fr": "Modèle récurrent", "es": "Plantilla recurrente"},
                "required": False,
                "default": None,
                "options": [],
                "type": "int",
            },
            "recurring_template_name": {
                "value": "No recurring template",
                "display_name": {"en": "Recurring Template", "fr": "Modèle récurrent", "es": "Plantilla recurrente"},
                "required": False,
                "default": "No recurring template",
                "options": [],
                "type": "string",
            },
            "created_by": {
                "value": 0,
                "display_name": {"en": "Created by", "fr": "Créé par", "es": "Creado por"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "created_by_username": {
                "value": "",
                "display_name": {"en": "Created by", "fr": "Créé par", "es": "Creado por"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "created_at": {
                "value": "",
                "display_name": {"en": "Created at", "fr": "Créé le", "es": "Creado el"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "updated_by": {
                "value": 0,
                "display_name": {"en": "Updated by", "fr": "Modifié par", "es": "Actualizado por"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "updated_by_username": {
                "value": "",
                "display_name": {"en": "Updated by", "fr": "Modifié par", "es": "Actualizado por"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "updated_at": {
                "value": "",
                "display_name": {"en": "Updated at", "fr": "Modifié le", "es": "Actualizado el"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
        }
        
        self.available_parameters = {
            "table": {
                "id": "r", "expense_date": "r", "category_id": "r", "description": "r",
                "amount": "r", "payment_method": "r", "reference": "r", "notes": "r",
                "recurring_template_id": "r", "created_by": "r", "created_by_username": "r",
                "created_at": "r", "updated_by": "r", "updated_by_username": "r", "updated_at": "r"
            },
            "dialog": {
                "expense_date": "rw", "category_id": "rw", "description": "rw",
                "amount": "rw", "payment_method": "rw", "reference": "rw",
                "notes": "rw", "recurring_template_id": "rw"
            },
            "database": {
                "id": "r", "expense_date": "rw", "category_id": "rw", "description": "rw",
                "amount": "rw", "payment_method": "rw", "reference": "rw", "notes": "rw",
                "recurring_template_id": "rw", "created_by": "r", "created_by_username": "r",
                "created_at": "r", "updated_by": "r", "updated_by_username": "r", "updated_at": "rw"
            },
            "report": {
                "id": "r", "expense_date": "r", "category_id": "r", "description": "r",
                "amount": "r", "payment_method": "r", "reference": "r", "notes": "r"
            },
        }

    def load_database_data(self):
        if not self.id or not self.database:
            return False
        record = self.database.get_charge(self.id)
        if not record:
            raise ValueError(f"Charge {self.id} does not exist")
        for key, value in record.items():
            if key in self.parameters:
                self.set_raw_value(key, value)
        return True


class ChargeRecurringTemplateClass:
    """Recurring charge template management"""
    
    def __init__(self, id, database):
        self.id = id
        self.database = database
        self.section = "Charge_Recurring_Templates"
        
        self.parameters = {
            "id": {
                "value": 0,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "name": {
                "value": "",
                "display_name": {"en": "Name", "fr": "Nom", "es": "Nombre"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string",
            },
            "category_id": {
                "value": 0,
                "display_name": {"en": "Category", "fr": "Catégorie", "es": "Categoría"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "default_amount": {
                "value": 0,
                "display_name": {"en": "Default Amount", "fr": "Montant par défaut", "es": "Monto por defecto"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "decimal",
                "precision": 2,
                "min": 0.01,
            },
            "frequency": {
                "value": "monthly",
                "display_name": {"en": "Frequency", "fr": "Fréquence", "es": "Frecuencia"},
                "required": True,
                "default": "monthly",
                "options": ["monthly", "weekly", "yearly"],
                "type": "string",
            },
            "next_due_date": {
                "value": "",
                "display_name": {"en": "Next Due Date", "fr": "Prochaine échéance", "es": "Próximo vencimiento"},
                "required": True,
                "default": "",
                "options": [],
                "type": "date",
            },
            "payment_method": {
                "value": "Cash",
                "display_name": {"en": "Payment Method", "fr": "Mode de paiement", "es": "Método de pago"},
                "required": False,
                "default": "Cash",
                "options": ["Cash", "Bank", "Check", "Card", "Other"],
                "type": "string",
            },
            "reference_template": {
                "value": "",
                "display_name": {"en": "Reference Template", "fr": "Modèle de référence", "es": "Plantilla de referencia"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "notes": {
                "value": "",
                "display_name": {"en": "Notes", "fr": "Notes", "es": "Notas"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
                "multiline": True,
            },
            "enabled": {
                "value": True,
                "display_name": {"en": "Enabled", "fr": "Activé", "es": "Activado"},
                "required": True,
                "default": True,
                "options": [],
                "type": "bool",
            },
            "created_by": {
                "value": 0,
                "display_name": {"en": "Created by", "fr": "Créé par", "es": "Creado por"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int",
            },
            "created_by_username": {
                "value": "",
                "display_name": {"en": "Created by", "fr": "Créé par", "es": "Creado por"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
            "created_at": {
                "value": "",
                "display_name": {"en": "Created at", "fr": "Créé le", "es": "Creado el"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
            },
        }
        
        self.available_parameters = {
            "table": {"id": "r", "name": "r", "category_id": "r", "default_amount": "r",
                     "frequency": "r", "next_due_date": "r", "payment_method": "r",
                     "reference_template": "r", "notes": "r", "enabled": "r",
                     "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "dialog": {"name": "rw", "category_id": "rw", "default_amount": "rw",
                      "frequency": "rw", "next_due_date": "rw", "payment_method": "rw",
                      "reference_template": "rw", "notes": "rw", "enabled": "rw"},
            "database": {"id": "r", "name": "rw", "category_id": "rw", "default_amount": "rw",
                        "frequency": "rw", "next_due_date": "rw", "payment_method": "rw",
                        "reference_template": "rw", "notes": "rw", "enabled": "rw",
                        "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "report": {"id": "r", "name": "r", "category_id": "r", "default_amount": "r",
                      "frequency": "r", "next_due_date": "r", "payment_method": "r",
                      "reference_template": "r", "notes": "r", "enabled": "r"},
        }
    
    def get_value(self, param_key=None, destination=None):
        if param_key:
            return self.parameters.get(param_key, {}).get("value")
        return {k: v.get("value") for k, v in self.parameters.items()}
    
    def set_value(self, param_key, value):
        if param_key in self.parameters:
            self.parameters[param_key]["value"] = value
    
    def get_display_name(self, param_key, language=None):
        if param_key in self.parameters:
            display_name = self.parameters[param_key].get("display_name", {})
            if language and language in display_name:
                return display_name[language]
            return display_name.get("en", param_key)
        return param_key
    
    def is_parameter_editable(self, param_key, destination='dialog'):
        return True
    
    def get_visible_parameters(self, destination='dialog'):
        return list(self.available_parameters.get(destination, {}).keys())
    
    def is_parameter_calculated(self, param_key):
        return False
    
    def save_to_database(self):
        pass
    
    def load_database_data(self):
        if self.id:
            pass
