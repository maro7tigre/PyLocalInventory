"""Single list of the entity classes backed by database tables.

Both the desktop window and the headless server register these, in this
order, so the two can never disagree about which tables exist.
"""
from classes.product_class import ProductClass
from classes.service_class import ServiceClass
from classes.door_type_class import DoorTypeClass
from classes.wood_type_class import WoodTypeClass
from classes.client_class import ClientClass
from classes.supplier_class import SupplierClass
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from classes.reports_class import ReportsClass

PARAMETER_CLASSES = (
    ProductClass,
    ServiceClass,
    DoorTypeClass,
    WoodTypeClass,
    ClientClass,
    SupplierClass,
    SalesClass,
    SalesItemClass,
    ImportClass,
    ImportItemClass,
    ReportsClass,
)


def register_all(database):
    """Register every entity class on ``database``."""
    for cls in PARAMETER_CLASSES:
        database.register_class(cls)
