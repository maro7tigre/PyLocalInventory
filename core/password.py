"""
Password management - handles authentication, validation, and session state
"""
from cryptography.fernet import Fernet
import base64


class PasswordManager:
    def __init__(self, profile_manager=None):
        self.profile_manager = profile_manager
        self.valid = False
        self._current_password = None
        self.validation_phrase = "Welcome to PyLocalInventory"
    
    def validate(self, password=None):
        """Validate provided password and return True/False"""
        if not self.profile_manager or not self.profile_manager.selected_profile:
            return False
            
        selected_profile = self.profile_manager.selected_profile
        
        # If profile has no encrypted phrase, it doesn't need a password yet
        if not selected_profile.encrypted_phrase:
            return False
        
        # If no password provided, check if we have a current password
        if password is None:
            password = self._current_password
        
        if not password:
            return False
        
        try:
            decrypted = self.decrypt_data(selected_profile.encrypted_phrase, password)
            is_valid = decrypted == self.validation_phrase
            if is_valid:
                self.valid = True
                self._current_password = password
            return is_valid
        except:
            return False
    
    def logout(self):
        """Clear current session and reset authentication state"""
        self.valid = False
        self._current_password = None
    
    def set_password(self, password):
        """Set new password for current session"""
        self._current_password = password
        self.valid = True
    
    def change_password(self, old_password, new_password):
        """Change existing password"""
        if not self.validate(old_password):
            return False
        
        if self.profile_manager and self.profile_manager.selected_profile:
            # Encrypt validation phrase with new password
            self.profile_manager.selected_profile.encrypted_phrase = self.encrypt_data(
                self.validation_phrase, new_password)
            self.profile_manager.selected_profile.save_to_config()
            self._current_password = new_password
            return True
        
        return False
    
    def _get_key(self, password):
        """Generate Fernet key from password"""
        if isinstance(password, str):
            password = password.encode()
        # Simple key derivation: base64 encode the password (padded to 32 bytes)
        key = base64.urlsafe_b64encode(password.ljust(32)[:32])
        return key
    
    def encrypt_data(self, data, password=None):
        """Encrypt data using password-derived key"""
        if password is None:
            password = self._current_password
        
        if not password:
            raise ValueError("No password available for encryption")
        
        key = self._get_key(password)
        fernet = Fernet(key)
        
        if isinstance(data, str):
            data = data.encode()
        
        return fernet.encrypt(data)
    
    def decrypt_data(self, encrypted_data, password=None):
        """Decrypt data using password-derived key"""
        if password is None:
            password = self._current_password
        
        if not password:
            raise ValueError("No password available for decryption")
        
        key = self._get_key(password)
        fernet = Fernet(key)
        
        decrypted_data = fernet.decrypt(encrypted_data)
        return decrypted_data.decode()