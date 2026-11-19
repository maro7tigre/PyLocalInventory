"""
Door Type Class - Stores individual door designs and serials
"""
from classes.base_class import BaseClass


class DoorTypeClass(BaseClass):
    def __init__(self, id=None, database=None, name=""):
        super().__init__(id, database)
        self.section = "Door_Types"
        self.parameters = {
            "name": {
                "value": name,
                "display_name": {"en": "Door Type", "fr": "Type de Porte", "es": "Tipo de Puerta"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "serial": {
                "value": 0,
                "display_name": {"en": "Serial", "fr": "Numéro", "es": "Número"},
                "required": True,
                "default": 0,
                "options": [],
                "type": "int",
                "min": 1
            },
            "image_path": {
                "value": None,
                "display_name": {"en": "Image", "fr": "Image", "es": "Imagen"},
                "required": False,
                "default": None,
                "options": [],
                "type": "image",
                "preview_size": 100
            }
        }

        self.available_parameters = {
            "table": {
                "name": "r",
                "serial": "r"
            },
            "dialog": {
                "name": "rw",
                "serial": "rw",
                "image_path": "rw"
            },
            "database": {
                "name": "rw",
                "serial": "rw",
                "image_path": "rw"
            }
        }

    def validate_serial_uniqueness(self, serial):
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return True

        try:
            self.database.cursor.execute(
                "SELECT COUNT(*) FROM Door_Types WHERE serial = %s AND ID != %s",
                (serial, self.id or 0)
            )
            result = self.database.cursor.fetchone()
            return result[0] == 0 if result else True
        except Exception as e:
            print(f"Error checking door type serial uniqueness: {e}")
            return True

    def validate_name_uniqueness(self, name):
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return True

        try:
            self.database.cursor.execute(
                "SELECT COUNT(*) FROM Door_Types WHERE name = %s AND ID != %s",
                (name, self.id or 0)
            )
            result = self.database.cursor.fetchone()
            return result[0] == 0 if result else True
        except Exception as e:
            print(f"Error checking door type name uniqueness: {e}")
            return True
