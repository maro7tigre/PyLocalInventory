"""
Password management - handles authentication, validation, and session state
"""
from cryptography.fernet import Fernet
import base64



class PasswordManager:
    def __init__(self, profile=None):
        self.profile = profile
        self.valid = False
        self._current_password = None
        self.validation_phrase = "Welocome to PyLocalInventory"
    
    def validate(self, password = None):
        """Validate provided password and return True/False"""
        if self.profile.validate():
            return self.decrypt_data(self.profile.selected_profile.encrypted_phrase, password) == self.validation_phrase
        return False
    
    def logout(self):
        """Clear current session and reset authentication state"""
        self.valid = False
        self._current_password = None
    
    def set_password(self, password):
        """Set new password for current profile"""
        self._current_password = password
    
    def change_password(self, old_password, new_password):
        """Change existing password"""
        pass
    
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
        
        key = self._get_key(password)
        fernet = Fernet(key)
        
        if isinstance(data, str):
            data = data.encode()
        
        return fernet.encrypt(data)
    
    def decrypt_data(self, encrypted_data, password=None):
        """Decrypt data using password-derived key"""
        if password is None:
            password = self._current_password
        
        key = self._get_key(password)
        fernet = Fernet(key)
        
        decrypted_data = fernet.decrypt(encrypted_data)
        return decrypted_data.decode()