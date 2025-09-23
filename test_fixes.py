#!/usr/bin/env python3

"""
Test script to verify that autocomplete fixes work properly
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classes.sales_item_class import SalesItemClass
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit

def test_autocomplete_widget():
    """Test that autocomplete widget handles callable options"""
    print("🔍 Testing AutoComplete Widget with callable options...")
    
    # Create a mock database-like object
    class MockDatabase:
        def __init__(self):
            self.cursor = self
        
        def execute(self, query):
            pass
        
        def fetchall(self):
            return [('Iron Bar',), ('Wood Plank',), ('Steel Rod',)]
    
    # Create sales item with mock database
    sales_item = SalesItemClass(1, MockDatabase())
    
    # Test that options is callable
    product_options = sales_item.parameters['product_name']['options']
    print(f"Product options is callable: {callable(product_options)}")
    
    # Test calling the options method
    try:
        options_list = product_options()
        print(f"Options list from method: {options_list}")
    except Exception as e:
        print(f"Error calling options method: {e}")
    
    # Test AutoCompleteLineEdit with callable options
    try:
        widget = AutoCompleteLineEdit(options=product_options)
        options_list = widget._get_options_list()
        print(f"AutoComplete widget options: {options_list}")
        print("✅ AutoComplete widget successfully handles callable options!")
    except Exception as e:
        print(f"❌ Error with AutoComplete widget: {e}")

def test_parameter_calculation():
    """Test that calculated parameters work correctly"""
    print("\\n🔗 Testing calculated parameters...")
    
    sales_item = SalesItemClass(1, None)
    
    # Test trying to set a calculated parameter (should raise error)
    try:
        sales_item.set_value('product_preview', '/some/path.jpg')
        print("❌ Should not be able to set calculated parameter!")
    except ValueError as e:
        print(f"✅ Correctly prevented setting calculated parameter: {e}")
    
    # Test setting a normal parameter (should work)
    try:
        sales_item.set_value('quantity', 5)
        print(f"✅ Successfully set quantity: {sales_item.get_value('quantity')}")
    except Exception as e:
        print(f"❌ Error setting normal parameter: {e}")

def main():
    print("🧪 Testing Autocomplete and Parameter Fixes")
    print("=" * 50)
    
    test_autocomplete_widget()
    test_parameter_calculation()
    
    print("\\n🎉 Test completed!")

if __name__ == "__main__":
    main()
