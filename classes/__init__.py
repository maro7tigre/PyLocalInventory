"""
Classes package initialization

Entity classes for PyLocalInventory including:
- Base class functionality
- Entity classes (Product, Client, Supplier)
- Operation classes (Sales, Import)
- Item classes (SalesItem, ImportItem)
"""

from .base_class import BaseClass
from .product_class import ProductClass
from .client_class import ClientClass
from .supplier_class import SupplierClass
from .sales_class import SalesClass
from .sales_item_class import SalesItemClass
from .import_class import ImportClass
from .import_item_class import ImportItemClass

__all__ = [
    # Base functionality
    'BaseClass',
    
    # Entity classes
    'ProductClass',
    'ClientClass',
    'SupplierClass',
    
    # Operation classes
    'SalesClass',
    'ImportClass',
    
    # Item classes
    'SalesItemClass',
    'ImportItemClass'
]