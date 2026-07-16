"""
Profile management module for handling profiles.
"""
import os
import json
import shutil
import time

from core.database import Database
from core.runtime_paths import portable_dir

class ProfileManager:
    def __init__(self):
        self.selected_profile : ProfileClass = None
        self.available_profiles = {}
        # Never depend on the process working directory. Windows Startup often
        # launches applications from a protected system directory.
        self.profiles_path = portable_dir("profiles")

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
            # Skip the deleted directory
            if item == "deleted":
                continue
                
            profile_dir = os.path.join(self.profiles_path, item)
            config_path = os.path.join(profile_dir, "config.json")
            
            if os.path.isdir(profile_dir) and os.path.exists(config_path):
                try:
                    profile = ProfileClass(item)
                    profile.config_path = config_path
                    profile.preview_path = os.path.join(profile_dir, "preview.png")  # Check for preview image
                    
                    # Load profile data from config
                    profile.load_config_data()
                    if not profile.database_name and not profile.schema_name:
                        profile.schema_name = Database._sanitize_schema_name(item)
                    
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
            profile.database_name = Database._profile_database_name(profile_data.get('company name') or profile_name)
            
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
        """Move profile to deleted directory except reports which are permanently deleted"""
        if profile_name not in self.available_profiles:
            return False
        
        profile = self.available_profiles[profile_name]
        profile_dir = os.path.dirname(profile.config_path)
        
        # Handle reports directory - delete permanently since they're temporary
        reports_dir = os.path.join(profile_dir, "reports")
        if os.path.exists(reports_dir):
            try:
                shutil.rmtree(reports_dir)
                print(f"Reports directory permanently deleted for profile '{profile_name}'")
            except Exception as e:
                print(f"Warning: Could not delete reports directory: {e}")
        
        # Create deleted directory if it doesn't exist
        deleted_dir = os.path.join(self.profiles_path, "deleted")
        os.makedirs(deleted_dir, exist_ok=True)
        
        # Generate unique name for deleted profile
        deleted_name = self._generate_deleted_profile_name(profile_name, deleted_dir)
        deleted_profile_path = os.path.join(deleted_dir, deleted_name)
        
        # Move profile directory to deleted directory
        if os.path.exists(profile_dir):
            try:
                shutil.move(profile_dir, deleted_profile_path)
                print(f"Profile '{profile_name}' moved to deleted/{deleted_name}")
            except Exception as e:
                print(f"Error moving profile to deleted directory: {e}")
                return False
        
        # Remove from memory
        del self.available_profiles[profile_name]
        
        # Clear selected profile if it was the deleted one
        if self.selected_profile and self.selected_profile.name == profile_name:
            self.selected_profile = None
        
        return True
    
    def _generate_deleted_profile_name(self, original_name, deleted_dir):
        """Generate unique name for deleted profile: originalname_deletiondate_number"""
        from datetime import datetime
        
        # Get current date in YYYY-MM-DD format
        deletion_date = datetime.now().strftime("%Y-%m-%d")
        
        # Start with base name
        base_name = f"{original_name}_{deletion_date}"
        
        # Check if base name already exists, if not return it
        if not os.path.exists(os.path.join(deleted_dir, base_name)):
            return base_name
        
        # If base name exists, add incrementing number
        counter = 1
        while True:
            candidate_name = f"{base_name}_{counter}"
            if not os.path.exists(os.path.join(deleted_dir, candidate_name)):
                return candidate_name
            counter += 1
    
    def list_profiles(self):
        """Get list of available profiles"""
        return list(self.available_profiles.keys())
    
    def duplicate_profile(self, source_name, new_name, database_name=None):
        """Duplicate an existing profile with a new name"""
        if source_name not in self.available_profiles:
            raise ValueError(f"Source profile '{source_name}' not found")
        
        if new_name in self.available_profiles:
            raise ValueError(f"Profile '{new_name}' already exists")
        
        source_profile = self.available_profiles[source_name]
        source_dir = os.path.dirname(source_profile.config_path)
        new_dir = os.path.join(self.profiles_path, new_name)
        
        # Create new profile directory structure (selective copying)
        os.makedirs(new_dir, exist_ok=True)
        
        # Copy config.json
        source_config = os.path.join(source_dir, "config.json")
        if os.path.exists(source_config):
            shutil.copy2(source_config, os.path.join(new_dir, "config.json"))
        
        # Copy preview.png if it exists
        source_preview = os.path.join(source_dir, "preview.png")
        if os.path.exists(source_preview):
            shutil.copy2(source_preview, os.path.join(new_dir, "preview.png"))
        
        # Copy images folder if it exists (but not backups)
        source_images = os.path.join(source_dir, "images")
        if os.path.exists(source_images):
            dest_images = os.path.join(new_dir, "images")
            shutil.copytree(source_images, dest_images)
        
        # Create new profile instance
        new_profile = ProfileClass(new_name)
        new_profile.config_path = os.path.join(new_dir, "config.json")
        new_profile.preview_path = os.path.join(new_dir, "preview.png")

        # Load and update the config
        new_profile.load_config_data()
        new_profile.database_name = database_name or Database._profile_database_name(
            new_profile.get_value('company name') or new_name
        )

        # Copy the source storage model into the new profile.
        if getattr(source_profile, 'database_name', None):
            from core import pg_backup
            pg_backup.clone_database(source_profile.database_name, new_profile.database_name)
        else:
            # Legacy fallback for older schema-based profiles.
            self._copy_database_tables(source_profile.schema_name, new_profile.schema_name)
        
        # Save updated config
        new_profile.save_to_config()
        
        # Add to available profiles
        self.available_profiles[new_name] = new_profile
        
        return new_profile
    
    def _copy_database_tables(self, source_schema, dest_schema):
        """Copy only specific tables (base data, not operations) from the source
        profile's Postgres schema into the destination profile's schema, within
        the one shared database - both schemas live side by side, so this is a
        same-database schema-to-schema copy rather than a file-to-file one."""
        import psycopg2
        from core.pg_config import load_server_config

        tables_to_copy = ['products', 'clients', 'suppliers']
        pg_config = load_server_config()

        try:
            conn = psycopg2.connect(
                host=pg_config.get('host'),
                port=pg_config.get('port'),
                dbname=pg_config.get('database'),
                user=pg_config.get('user'),
                password=pg_config.get('password'),
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {dest_schema}")
            conn.commit()

            for table_name in tables_to_copy:
                try:
                    # Skip if the source table doesn't exist yet
                    cursor.execute("SELECT to_regclass(%s)", (f"{source_schema}.{table_name}",))
                    if not cursor.fetchone()[0]:
                        continue

                    cursor.execute(
                        f"CREATE TABLE IF NOT EXISTS {dest_schema}.{table_name} "
                        f"(LIKE {source_schema}.{table_name} INCLUDING ALL)"
                    )
                    cursor.execute(f"INSERT INTO {dest_schema}.{table_name} SELECT * FROM {source_schema}.{table_name}")

                    cursor.execute(f"SELECT MAX(id) FROM {dest_schema}.{table_name}")
                    max_id = cursor.fetchone()[0]
                    if max_id is not None:
                        cursor.execute(
                            f"SELECT setval(pg_get_serial_sequence('{dest_schema}.{table_name}', 'id'), %s)",
                            (max_id,)
                        )

                    conn.commit()
                    cursor.execute(f"SELECT COUNT(*) FROM {dest_schema}.{table_name}")
                    print(f"✓ Copied {cursor.fetchone()[0]} records from {table_name}")

                except Exception as e:
                    conn.rollback()
                    print(f"✗ Error copying table {table_name}: {e}")
                    continue

            conn.close()
            print(f"✓ Database tables copied successfully to schema {dest_schema}")

        except Exception as e:
            print(f"✗ Error copying database: {e}")
    
    
class ProfileClass:
    def __init__(self, name):
        self.name = name
        self.preview_path = None
        self.encrypted_phrase = None  # Placeholder for encrypted validation phrase
        self.config_path = "./config.json"
        self.database_name = None
        self.schema_name = None
        self.parameters = {
            "company name": {"value": None, "display name": {"en" : "company name","fr": "nom de l'entreprise", "es": "nombre de la empresa"}, "required": True, "default": "Lamibois", "options": ["Lamidap", "Lamibois", "porte amazone"], "type": "string"},
            "address": {"value": None, "display name": {"en" : "address","fr": "adresse", "es": "dirección"}, "required": False, "default": "", "options": [], "type": "string"},
            "email": {"value": None, "display name": {"en" : "email", "fr": "email", "es": "correo electrónico"}, "required": False, "default": "", "options": [], "type": "string"},
            "phone": {"value": None, "display name": {"en" : "phone", "fr": "téléphone", "es": "teléfono"}, "required": False, "default": "", "options": [], "type": "string"},
            # Multiline footer text that will appear centered at the bottom of the last report page
            "report footer": {"value": None, "display name": {"en" : "report footer", "fr": "pied de page du rapport", "es": "pie de informe"}, "required": False, "default": "", "options": [], "type": "text"},
            "currency": {"value": None, "display name": {"en" : "currency","fr": "devise", "es": "moneda"}, "required": False, "default": "DA", "options": [], "type": "string"}
        }
        self.available_parameters = {
            # Order determines display order in dialog
            "dialog" : ["company name", "address", "email", "phone", "report footer"],
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

                if "database_name" in data:
                    self.database_name = data["database_name"]

                if "schema_name" in data:
                    self.schema_name = data["schema_name"]
                
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

                if self.database_name:
                    data["database_name"] = self.database_name

                if self.schema_name:
                    data["schema_name"] = self.schema_name
                
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
