"""
Wood Type Class - Stores available wood finishes for services
"""
from classes.base_class import BaseClass


class WoodTypeClass(BaseClass):
    def __init__(self, id=None, database=None, name=""):
        super().__init__(id, database)
        self.section = "Wood_Types"
        self.parameters = {
            "name": {
                "value": name,
                "display_name": {"en": "Wood Type", "fr": "Type de Bois", "es": "Tipo de Madera"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            }
        }

        self.available_parameters = {
            "table": {
                "name": "r"
            },
            "dialog": {
                "name": "rw"
            },
            "database": {
                "name": "rw"
            }
        }

    def validate_name_uniqueness(self, name):
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return True

        try:
            self.database.cursor.execute(
                "SELECT COUNT(*) FROM Wood_Types WHERE name = %s AND ID != %s",
                (name, self.id or 0)
            )
            result = self.database.cursor.fetchone()
            return result[0] == 0 if result else True
        except Exception as e:
            print(f"Error checking wood type name uniqueness: {e}")
            return True
