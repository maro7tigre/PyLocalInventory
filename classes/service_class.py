"""
Service Class - New entity for service management
"""
from classes.base_class import BaseClass


class ServiceClass(BaseClass):
    def __init__(self, id, database, name=""):
        super().__init__(id, database)
        self.section = "Services"
        self.parameters = {
            "id": {
                "value": id,
                "display_name": {"en": "ID", "fr": "ID", "es": "ID"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "service_code": {
                "value": "",
                "display_name": {"en": "Code", "fr": "Code", "es": "Código"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "service_type": {
                "value": "Door Service",
                "display_name": {"en": "Service Type", "fr": "Type de Service", "es": "Tipo de Servicio"},
                "required": True,
                "default": "Door Service",
                "options": ["Door Service", "Custom Service"],
                "type": "string"
            },
            "name": {
                "value": name,
                "display_name": {"en": "Service Name", "fr": "Nom du Service", "es": "Nombre del Servicio"},
                "required": True,
                "default": "",
                "options": [],
                "type": "string"
            },
            "door_type_id": {
                "value": 0,
                "display_name": {"en": "Door Type ID", "fr": "ID du Type de Porte", "es": "ID del Tipo de Puerta"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "door_type_name": {
                "value": "",
                "display_name": {"en": "Door Type", "fr": "Type de Porte", "es": "Tipo de Puerta"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "door_type_serial": {
                "value": 0,
                "display_name": {"en": "Door Type Number", "fr": "Numéro de Porte", "es": "Número de Puerta"},
                "required": False,
                "default": 0,
                "options": [],
                "type": "int"
            },
            "door_type_image_path": {
                "value": None,
                "display_name": {"en": "Door Image", "fr": "Image de Porte", "es": "Imagen de Puerta"},
                "required": False,
                "default": None,
                "options": [],
                "type": "string"
            },
            "wood_type": {
                "value": "",
                "display_name": {"en": "Wood Type", "fr": "Type de Bois", "es": "Tipo de Madera"},
                "required": False,
                "default": "",
                "options": ["NOGAL", "CHENE", "HETRE", "FREINE"],
                "type": "string"
            },
            "length": {
                "value": 0.0,
                "display_name": {"en": "Length", "fr": "Longueur", "es": "Longitud"},
                "required": False,
                "default": 0.0,
                "options": [],
                "type": "float",
                "min": 0.0
            },
            "width": {
                "value": 0.0,
                "display_name": {"en": "Width", "fr": "Largeur", "es": "Anchura"},
                "required": False,
                "default": 0.0,
                "options": [],
                "type": "float",
                "min": 0.0
            },
            "thickness": {
                "value": 0.0,
                "display_name": {"en": "Thickness", "fr": "Épaisseur", "es": "Grosor"},
                "required": False,
                "default": 0.0,
                "options": [],
                "type": "float",
                "min": 0.0
            },
            "unit": {
                "value": "cm",
                "display_name": {"en": "Unit", "fr": "Unité", "es": "Unidad"},
                "required": False,
                "default": "cm",
                "options": ["cm", "m"],
                "type": "string"
            },
            "color": {
                "value": "",
                "display_name": {"en": "Color", "fr": "Couleur", "es": "Color"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "description": {
                "value": "",
                "display_name": {"en": "Description", "fr": "Description", "es": "Descripción"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string"
            },
            "information": {
                "value": "",
                "display_name": {"en": "Information", "fr": "Informations", "es": "Información"},
                "required": False,
                "default": "",
                "options": [],
                "type": "string",
                "method": self._calculate_information
            }
        }
        self.available_parameters = {
            "table": {
                "id": "r",
                "service_code": "r",
                "name": "r",
                "information": "r",
                "description": "r"
            },
            "dialog": {
                "service_code": "rw",
                "service_type": "rw",
                "name": "rw",
                "door_type_id": "rw",
                "door_type_name": "rw",
                "door_type_serial": "r",
                "door_type_image_path": "r",
                "wood_type": "rw",
                "length": "rw",
                "width": "rw",
                "thickness": "rw",
                "unit": "rw",
                "color": "rw",
                "description": "rw"
            },
            "database": {
                "service_code": "rw",
                "service_type": "rw",
                "name": "rw",
                "door_type_id": "rw",
                "door_type_name": "rw",
                "door_type_serial": "rw",
                "door_type_image_path": "rw",
                "wood_type": "rw",
                "length": "rw",
                "width": "rw",
                "thickness": "rw",
                "unit": "rw",
                "color": "rw",
                "description": "rw"
            },
            "report": {
                "service_code": "r",
                "service_type": "r",
                "name": "r",
                "description": "r"
            }
        }

    @staticmethod
    def generate_door_code(wood_type, door_serial):
        wood_mapping = {
            'NOGAL': 'N',
            'CHENE': 'C',
            'HETRE': 'H',
            'FREINE': 'F'
        }

        if wood_type is None:
            wood_type = ""

        wood_letter = wood_mapping.get(str(wood_type).upper(), "")
        if not wood_letter and str(wood_type).strip():
            wood_letter = str(wood_type).strip()[0].upper()

        try:
            serial_num = int(door_serial)
            serial_str = f"{serial_num:03d}"
        except (ValueError, TypeError):
            serial_str = str(door_serial).zfill(3) if door_serial is not None else ""

        if not wood_letter or not serial_str:
            return ""

        return f"P{wood_letter}{serial_str}"

    def _calculate_information(self):
        """Calculate the service information summary displayed in the table."""
        service_type = self.get_value('service_type')
        if service_type != 'Door Service':
            return '-' if self.get_value('description') else '-'

        color = self.get_value('color') or ''
        length = self.get_value('length') or 0.0
        width = self.get_value('width') or 0.0
        thickness = self.get_value('thickness') or 0.0
        unit = self.get_value('unit') or 'cm'

        if unit == 'm':
            length_str = f"L: {length:.2f} m"
            width_str = f"W: {width:.2f} m"
            thickness_str = f"T: {thickness:.2f} m"
        else:
            length_str = f"L: {length:.2f} cm"
            width_str = f"W: {width:.2f} cm"
            thickness_str = f"T: {thickness:.2f} cm"

        color_part = f"Color: {color} | " if color else ""
        return f"{color_part}{length_str} × {width_str} × {thickness_str}"

