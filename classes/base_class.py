"""
Updated Base Class with improved parameter handling
"""

class BaseClass:
    def __init__(self, id, database):
        self.section = "Base"
        self.id = id
        self.database = database
        self.parameters = {}
        self.available_parameters = {}
        
    def get_value(self, param_key=None, destination=None):
        """Get parameter value(s) - handles calculated parameters"""
        if param_key:
            # Single parameter
            if param_key not in self.parameters:
                return None
            
            param_info = self.parameters[param_key]
            
            # Check if it's a calculated parameter
            if 'method' in param_info and param_info['method'] is not None:
                try:
                    return param_info['method']()
                except Exception as e:
                    print(f"Error calculating {param_key}: {e}")
                    return param_info.get('default', None)
            else:
                return param_info.get("value", param_info.get('default', None))
        
        elif destination:
            # Multiple parameters for specific destination
            allowed_keys = self.available_parameters.get(destination, {})
            result = {}
            
            for key in allowed_keys:
                if key in self.parameters:
                    value = self.get_value(key)  # Use recursive call to handle calculated values
                    result[key] = value
            
            return result
        
        else:
            # All parameters
            result = {}
            for key in self.parameters:
                value = self.get_value(key)  # Use recursive call to handle calculated values
                result[key] = value
            return result
        
    def set_value(self, param_key, value):
        """Set parameter value - only for non-calculated parameters"""
        if param_key not in self.parameters:
            raise KeyError(f"Parameter '{param_key}' not found in {self.section} class.")
        
        param_info = self.parameters[param_key]
        
        # Check if it's a calculated parameter
        if 'method' in param_info and param_info['method'] is not None:
            raise ValueError(f"Cannot set value for calculated parameter '{param_key}'")
        
        # Type validation and conversion
        param_type = param_info.get('type', 'string')
        
        if param_type == 'int' and value is not None:
            try:
                value = int(float(value))  # Handle string numbers
            except (ValueError, TypeError):
                raise ValueError(f"Invalid integer value for '{param_key}': {value}")
        
        elif param_type == 'float' and value is not None:
            try:
                value = float(value)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid float value for '{param_key}': {value}")
        
        elif param_type == 'string' and value is not None:
            value = str(value)
        
        # Set the value
        self.parameters[param_key]["value"] = value
        
    def set_values(self, values_dict):
        """Set multiple parameter values"""
        for key, value in values_dict.items():
            try:
                self.set_value(key, value)
            except (KeyError, ValueError) as e:
                print(f"Warning: Could not set {key}={value}: {e}")
    
    def get_display_name(self, param_key, language='en'):
        """Get localized display name for parameter"""
        if param_key not in self.parameters:
            return param_key
        
        display_names = self.parameters[param_key].get('display_name', {})
        return display_names.get(language, display_names.get('en', param_key))
    
    def is_parameter_editable(self, param_key, destination='dialog'):
        """Check if parameter is editable in given destination"""
        if destination not in self.available_parameters:
            return False
        
        permission = self.available_parameters[destination].get(param_key, '')
        return 'w' in permission.lower()
    
    def is_parameter_visible(self, param_key, destination='dialog'):
        """Check if parameter is visible in given destination"""
        if destination not in self.available_parameters:
            return False
        
        return param_key in self.available_parameters[destination]
    
    def get_visible_parameters(self, destination='dialog'):
        """Get list of parameters visible in destination"""
        if destination not in self.available_parameters:
            return []
        
        return list(self.available_parameters[destination].keys())
    
    def is_parameter_calculated(self, param_key):
        """Check if parameter is calculated (has method)"""
        if param_key not in self.parameters:
            return False
        
        param_info = self.parameters[param_key]
        return 'method' in param_info and param_info['method'] is not None
    
    def validate_parameter(self, param_key, value):
        """Validate parameter value against constraints"""
        if param_key not in self.parameters:
            return False, f"Parameter '{param_key}' not found"
        
        param_info = self.parameters[param_key]
        
        # Check required
        if param_info.get('required', False) and not value:
            return False, f"{self.get_display_name(param_key)} is required"
        
        # Check type-specific constraints
        param_type = param_info.get('type', 'string')
        
        if param_type in ['int', 'float'] and value is not None:
            try:
                num_value = float(value)
                
                min_val = param_info.get('min')
                max_val = param_info.get('max')
                
                if min_val is not None and num_value < min_val:
                    return False, f"{self.get_display_name(param_key)} must be at least {min_val}"
                
                if max_val is not None and num_value > max_val:
                    return False, f"{self.get_display_name(param_key)} must be at most {max_val}"
                
            except (ValueError, TypeError):
                return False, f"{self.get_display_name(param_key)} must be a valid number"
        
        elif param_type == 'string':
            # Check if value is in options (if options are specified)
            options = param_info.get('options', [])
            if options and value and value not in options:
                return False, f"{self.get_display_name(param_key)} must be one of: {', '.join(options)}"
        
        return True, ""
    
    def load_database_data(self):
        """Load data from database - override in subclasses"""
        if not self.database or not self.id:
            return False
        
        try:
            items = self.database.get_items(self.section)
            for item in items:
                if item.get('ID') == self.id:
                    # Load values from database item
                    for param_key in self.parameters:
                        if param_key in item and not self.is_parameter_calculated(param_key):
                            self.set_value(param_key, item[param_key])
                    return True
            return False
        except Exception as e:
            print(f"Error loading data for {self.section} {self.id}: {e}")
            return False
    
    def save_to_database(self):
        """Save data to database - override in subclasses"""
        if not self.database:
            return False
        
        try:
            data = self.get_value(destination="database")
            
            if self.id and self.id > 0:
                # Update existing
                return self.database.update_item(self.id, data, self.section)
            else:
                # Add new
                return self.database.add_item(data, self.section)
        except Exception as e:
            print(f"Error saving {self.section}: {e}")
            return False
    
    def get_quantity(self):
        """Get quantity - override in subclasses that need it"""
        return 0