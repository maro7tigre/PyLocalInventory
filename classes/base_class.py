
class BaseClass:
    def __init__(self, id, database):
        self.section = "Base"
        self.id = id
        self.database = database
        self.parameters = {}
        self.available_parameters = {}
        
    def get_value(self, param_key=None, distination=None):
        if param_key:
            return self.parameters.get(param_key, {}).get("value", None)
        elif distination:
            allowed_keys = self.available_parameters.get(distination, [])
            return {key: self.parameters[key]["value"] for key in allowed_keys if key in self.parameters}
        else:
            return {key: param["value"] for key, param in self.parameters.items()}
        
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
    
    def load_database_data(self):
        pass #TODO: implement loading data from database
    
    def save_to_database(self):
        pass #TODO: implement saving data to database
        
    def get_quantity(self):
        #TODO: implement quantity retrieval from database
        pass