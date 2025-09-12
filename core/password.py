"""
Password management - handles authentication, validation, and session state
"""
from cryptography.fernet import Fernet



class PasswordManager:
    def __init__(self, profile=None):
        self.profile = profile
        self.valid = False
        self._current_password = None
        self.validation_phrase = "Welocome to PyLocalInventory"
    
    def validate(self, password = None):
        """Validate provided password and return True/False"""
        return self.decrypt_data(self.profile.encrypted_phrase, password) == self.validation_phrase
    
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
    
    
    
    def encrypt_data(self, data):
        pass
    
    def decrypt_data(self, encrypted_data, password):
        if password is None:
            password = self._current_password
            
        pass