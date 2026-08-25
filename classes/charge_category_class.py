"""
Charge Category Class
"""
from classes.base_class import BaseClass


class ChargeCategoryClass(BaseClass):
    """Charge category management"""
    
    def __init__(self, id, database):
        super().__init__(id, database)
        self.section = "Charge_Categories"
        
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Define parameters for charge categories
        cls.parameters = {
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
                "maxlength": 100,
            },
            "active": {
                "value": True,
                "display_name": {"en": "Active", "fr": "Actif", "es": "Activo"},
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
        cls.available_parameters = {
            "table": {"id": "r", "name": "r", "active": "r", "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "dialog": {"name": "rw", "active": "rw"},
            "database": {"id": "r", "name": "rw", "active": "rw", "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "report": {"id": "r", "name": "r", "active": "r"},
        }


class ChargeCategoryClass(ChargeCategoryClass):
    """Wrapper for Charge Category - double definition to avoid import issues"""
    pass


# The actual class
class ChargeCategoryClass:
    """Charge category management"""
    
    def __init__(self, id, database):
        self.id = id
        self.database = database
        self.section = "Charge_Categories"
        
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
                "maxlength": 100,
            },
            "active": {
                "value": True,
                "display_name": {"en": "Active", "fr": "Actif", "es": "Activo"},
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
            "table": {"id": "r", "name": "r", "active": "r", "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "dialog": {"name": "rw", "active": "rw"},
            "database": {"id": "r", "name": "rw", "active": "rw", "created_by": "r", "created_by_username": "r", "created_at": "r"},
            "report": {"id": "r", "name": "r", "active": "r"},
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
            # Load from database
            pass