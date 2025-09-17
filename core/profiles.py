"""
Profile management module for handling profiles.
"""

class ProfileManager:
    def __init__(self):
        self.selected_profile : ProfileClass = None
        self.available_profiles = {}

        self.empty_profile = ProfileClass("")
        empty_values = {
            "company name": "",
            "address": "",
            "email": "",
            "phone": ""
        }
        self.empty_profile.set_values(empty_values)
        self.new_profile = ProfileClass("")
        
        self.load_profiles()
    
    def load_profiles(self):
        pass
        
    def validate(self, profile=None):
        """Check if current profile is valid"""
        if profile is None:
            profile= self.selected_profile
        #TODO: implement actual validation logic
            
        return False
    
    def logout(self):
        """Clear current profile and reset state"""
        pass
    
    def load_profile(self, profile_name):
        """Load specified profile"""
        pass
    
    def create_profile(self, profile_name):
        """Create new profile"""
        pass
    
    def delete_profile(self, profile_name):
        """Delete existing profile"""
        pass
    
    def list_profiles(self):
        """Get list of available profiles"""
        pass
    
    def validate_profile(self):
        """Check if current profile is valid"""
        pass
    
    
class ProfileClass:
    def __init__(self, name):
        self.name = name
        self.preview_path = None
        self.encrypted_phrase = None  # Placeholder for encrypted validation phrase
        self.config_path = "./config.json"
        self.database_path = "./database.db"
        self.parameters = {
            "company name": {"value": None, "display name": {"en" : "company name","fr": "nom de l'entreprise", "es": "nombre de la empresa"}, "required": True, "default": "Lamibois", "options": ["Lamidap", "Lamibois", "porte amazone"], "type": "string"},
            "address": {"value": None, "display name": {"en" : "address","fr": "adresse", "es": "dirección"}, "required": True, "default": "", "options": [], "type": "string"},
            "email": {"value": None, "display name": {"en" : "email", "fr": "email", "es": "correo electrónico"}, "required": False, "default": "", "options": [], "type": "string"},
            "phone": {"value": None, "display name": {"en" : "phone", "fr": "téléphone", "es": "teléfono"}, "required": False, "default": "", "options": [], "type": "string"}
        }
        self.available_parameters = {
            "dialog" : ["company name", "address", "email", "phone"],
            "table" : ["company name"]
        }
        
    def get_value(self, param_key=None, distination=None):
        if param_key:
            return self.parameters.get(param_key, {}).get("value", None)
        elif distination:
            allowed_keys = self.available_parameters.get(distination, [])
            return {key: self.parameters[key]["value"] for key in allowed_keys if key in self.parameters}
        else:
            return {key: param["value"] for key, param in self.parameters.items()}
    
    def get_parameter_info(self, param_key, info_key):
        """Get specific parameter information like 'default', 'required', etc."""
        return self.parameters.get(param_key, {}).get(info_key, None)
    
    def get_display_name(self, param_key, language):
        """Get display name for parameter in specified language"""
        param_data = self.parameters.get(param_key, {})
        display_names = param_data.get("display name", {})
        return display_names.get(language, param_key)  # Fallback to key if language not found
        
    def set_value(self, param_key, value):
        if param_key in self.parameters:
            self.parameters[param_key]["value"] = value
        else:
            raise KeyError(f"Parameter '{param_key}' not found in product class.")
        
    def set_values(self, values_dict):
        for key, value in values_dict.items():
            if key in self.parameters:
                self.parameters[key]["value"] = value
            else:
                raise KeyError(f"Parameter '{key}' not found in product class.")
    
    def load_config_data(self):
        pass #TODO: implement loading data from database
    
    def save_to_config(self):
        pass #TODO: implement saving data to database