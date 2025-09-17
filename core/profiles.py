"""
Profile management module for handling profiles.
"""
import os
import json
import shutil
import time

class ProfileManager:
    def __init__(self):
        self.selected_profile : ProfileClass = None
        self.available_profiles = {}
        self.profiles_path = "./profiles"

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
        """Load profiles from filesystem by scanning directories with config.json"""
        self.available_profiles = {}
        
        if not os.path.exists(self.profiles_path):
            os.makedirs(self.profiles_path)
            return
        
        for item in os.listdir(self.profiles_path):
            profile_dir = os.path.join(self.profiles_path, item)
            config_path = os.path.join(profile_dir, "config.json")
            
            if os.path.isdir(profile_dir) and os.path.exists(config_path):
                try:
                    profile = ProfileClass(item)
                    profile.config_path = config_path
                    profile.database_path = os.path.join(profile_dir, f"{item}.db")
                    profile.preview_path = os.path.join(profile_dir, "preview.png")  # Check for preview image
                    
                    # Load profile data from config
                    profile.load_config_data()
                    
                    self.available_profiles[item] = profile
                except Exception as e:
                    print(f"Failed to load profile {item}: {e}")
                    continue
        
    def validate(self, profile=None):
        """Check if current profile is valid"""
        if profile is None:
            profile = self.selected_profile
        
        return profile is not None and os.path.exists(profile.config_path)
    
    def logout(self):
        """Clear current profile and reset state"""
        self.selected_profile = None
    
    def load_profile(self, profile_name):
        """Load specified profile"""
        if profile_name in self.available_profiles:
            self.selected_profile = self.available_profiles[profile_name]
            return True
        return False
    
    def create_profile(self, profile_data, preview_image_path=None):
        """Create new profile with given data"""
        profile_name = profile_data.get('name', '').strip()
        if not profile_name:
            raise ValueError("Profile name cannot be empty")
        
        profile_dir = os.path.join(self.profiles_path, profile_name)
        if os.path.exists(profile_dir):
            raise ValueError(f"Profile '{profile_name}' already exists")
        
        # Create profile directory
        os.makedirs(profile_dir)
        
        try:
            # Create profile instance
            profile = ProfileClass(profile_name)
            profile.config_path = os.path.join(profile_dir, "config.json")
            profile.database_path = os.path.join(profile_dir, f"{profile_name}.db")
            
            # Set profile data
            for key, value in profile_data.items():
                if key != 'name':  # name is already set
                    profile.set_value(key, value)
            
            # Handle preview image
            if preview_image_path and os.path.exists(preview_image_path):
                preview_dest = os.path.join(profile_dir, "preview.png")
                shutil.copy2(preview_image_path, preview_dest)
                profile.preview_path = preview_dest
            
            # Save to filesystem
            profile.save_to_config()
            
            # Add to available profiles
            self.available_profiles[profile_name] = profile
            
            return profile
        except Exception as e:
            # Clean up on failure
            if os.path.exists(profile_dir):
                shutil.rmtree(profile_dir)
            raise e
    
    def update_profile(self, profile_name, profile_data, preview_image_path=None):
        """Update existing profile"""
        if profile_name not in self.available_profiles:
            raise ValueError(f"Profile '{profile_name}' not found")
        
        profile = self.available_profiles[profile_name]
        profile_dir = os.path.dirname(profile.config_path)
        
        # Update profile data
        for key, value in profile_data.items():
            if key != 'name':  # Don't allow name changes for now
                profile.set_value(key, value)
        
        # Handle preview image update
        if preview_image_path and os.path.exists(preview_image_path):
            preview_dest = os.path.join(profile_dir, "preview.png")
            shutil.copy2(preview_image_path, preview_dest)
            profile.preview_path = preview_dest
        
        # Save changes
        profile.save_to_config()
    
    def delete_profile(self, profile_name):
        """Delete existing profile"""
        if profile_name not in self.available_profiles:
            return False
        
        profile = self.available_profiles[profile_name]
        profile_dir = os.path.dirname(profile.config_path)
        
        # Remove from filesystem
        if os.path.exists(profile_dir):
            shutil.rmtree(profile_dir)
        
        # Remove from memory
        del self.available_profiles[profile_name]
        
        # Clear selected profile if it was the deleted one
        if self.selected_profile and self.selected_profile.name == profile_name:
            self.selected_profile = None
        
        return True
    
    def list_profiles(self):
        """Get list of available profiles"""
        return list(self.available_profiles.keys())
    
    def duplicate_profile(self, source_name, new_name):
        """Duplicate an existing profile with a new name"""
        if source_name not in self.available_profiles:
            raise ValueError(f"Source profile '{source_name}' not found")
        
        if new_name in self.available_profiles:
            raise ValueError(f"Profile '{new_name}' already exists")
        
        source_profile = self.available_profiles[source_name]
        source_dir = os.path.dirname(source_profile.config_path)
        new_dir = os.path.join(self.profiles_path, new_name)
        
        # Copy entire profile directory
        shutil.copytree(source_dir, new_dir)
        
        # Create new profile instance
        new_profile = ProfileClass(new_name)
        new_profile.config_path = os.path.join(new_dir, "config.json")
        new_profile.database_path = os.path.join(new_dir, f"{new_name}.db")
        new_profile.preview_path = os.path.join(new_dir, "preview.png")
        
        # Load and update the config
        new_profile.load_config_data()
        
        # Rename database file if it exists
        old_db = os.path.join(new_dir, f"{source_name}.db")
        new_db = new_profile.database_path
        if os.path.exists(old_db):
            os.rename(old_db, new_db)
        
        # Save updated config
        new_profile.save_to_config()
        
        # Add to available profiles
        self.available_profiles[new_name] = new_profile
        
        return new_profile
    
    
class ProfileClass:
    def __init__(self, name):
        self.name = name
        self.preview_path = None
        self.encrypted_phrase = None  # Placeholder for encrypted validation phrase
        self.config_path = "./config.json"
        self.database_path = "./database.db"
        self.parameters = {
            "company name": {"value": None, "display name": {"en" : "company name","fr": "nom de l'entreprise", "es": "nombre de la empresa"}, "required": True, "default": "Lamibois", "options": ["Lamidap", "Lamibois", "porte amazone"], "type": "string"},
            "address": {"value": None, "display name": {"en" : "address","fr": "adresse", "es": "dirección"}, "required": False, "default": "", "options": [], "type": "string"},
            "email": {"value": None, "display name": {"en" : "email", "fr": "email", "es": "correo electrónico"}, "required": False, "default": "", "options": [], "type": "string"},
            "phone": {"value": None, "display name": {"en" : "phone", "fr": "téléphone", "es": "teléfono"}, "required": False, "default": "", "options": [], "type": "string"}
        }
        self.available_parameters = {
            "dialog" : ["company name", "address", "email", "phone"],
            "table" : ["company name"]
        }
        
    def get_value(self, param_key=None, destination=None):
        if param_key:
            return self.parameters.get(param_key, {}).get("value", None)
        elif destination:
            allowed_keys = self.available_parameters.get(destination, [])
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
            raise KeyError(f"Parameter '{param_key}' not found in profile class.")
        
    def set_values(self, values_dict):
        for key, value in values_dict.items():
            if key in self.parameters:
                self.parameters[key]["value"] = value
            else:
                raise KeyError(f"Parameter '{key}' not found in profile class.")
    
    def load_config_data(self):
        """Load profile data from JSON config file"""
        if not os.path.exists(self.config_path):
            return
        
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Load parameter values
                for key in self.parameters:
                    if key in data:
                        self.parameters[key]["value"] = data[key]
                
                # Load encrypted phrase if exists
                if "encrypted_phrase" in data:
                    self.encrypted_phrase = bytes.fromhex(data["encrypted_phrase"])
                
                return  # Success, exit retry loop
                
            except (OSError, IOError) as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"Failed to load config for profile {self.name} after {max_retries} attempts: {e}")
            except Exception as e:
                print(f"Failed to load config for profile {self.name}: {e}")
                break
    
    def save_to_config(self):
        """Save profile data to JSON config file"""
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                data = {}
                
                # Save parameter values
                for key, param in self.parameters.items():
                    if param["value"] is not None:
                        data[key] = param["value"]
                
                # Save encrypted phrase if exists
                if self.encrypted_phrase:
                    data["encrypted_phrase"] = self.encrypted_phrase.hex()
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                
                # Write to temporary file first, then rename for atomic operation
                temp_path = self.config_path + '.tmp'
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Atomic rename to replace the original file
                if os.name == 'nt':  # Windows
                    if os.path.exists(self.config_path):
                        os.remove(self.config_path)
                    os.rename(temp_path, self.config_path)
                else:  # Unix-like systems
                    os.rename(temp_path, self.config_path)
                
                return  # Success, exit retry loop
                
            except (OSError, IOError) as e:
                # Clean up temp file if it exists
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"Failed to save config for profile {self.name} after {max_retries} attempts: {e}")
                    raise e
            except Exception as e:
                # Clean up temp file if it exists
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                print(f"Failed to save config for profile {self.name}: {e}")
                raise e