import sys
from PySide6.QtWidgets import (QApplication, QLineEdit, QCompleter, QVBoxLayout, 
                               QWidget, QLabel, QTableWidget, QStyledItemDelegate, 
                               QTableWidgetItem, QHBoxLayout)
from PySide6.QtCore import Qt, QStringListModel


class AutoCompleteLineEdit(QLineEdit):
    """Custom QLineEdit with smart autocomplete functionality"""
    
    def __init__(self, parent=None, options=None):
        super().__init__(parent)
        self.options = options or []
        self.completer = None
        self.suggestions_frozen = False
        
        # Set default background for table editing
        self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; }")
        
        # Connect signals for autocomplete functionality
        self.textChanged.connect(self._update_autocomplete)
        self.editingFinished.connect(self._handle_edit_finished)
        self._setup_completer()
    
    def keyPressEvent(self, event):
        """Handle arrow keys to freeze suggestions"""
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.suggestions_frozen = True
        else:
            self.suggestions_frozen = False
        
        super().keyPressEvent(event)
    
    def _get_options_list(self):
        """Get the actual options list, calling method if necessary"""
        if callable(self.options):
            try:
                return self.options() or []
            except Exception as e:
                print(f"Error calling options method: {e}")
                return []
        return self.options or []
    
    def _setup_completer(self):
        """Initialize completer if options are available"""
        options_list = self._get_options_list()
        if not options_list:
            if self.completer:
                self.setCompleter(None)
                self.completer = None
            return

        if not self.completer:
            self.completer = QCompleter(self)
            self.completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.completer.setMaxVisibleItems(3)
            self.completer.setCompletionMode(QCompleter.PopupCompletion)
            self.completer.setFilterMode(Qt.MatchContains)
            self.setCompleter(self.completer)
    
    def _calculate_suggestions(self, text):
        """Calculate suggestions with scoring system"""
        options_list = self._get_options_list()
        if not text.strip():
            return {option: 1 for option in options_list}
        
        input_words = text.lower().split()
        suggestions = {}
        
        for option in options_list:
            option_words = option.lower().split()
            score = 0
            
            # Check if option starts with full input string
            if option.lower().startswith(text.lower()):
                score += 3
            
            # Check each input word against option words
            for i, input_word in enumerate(input_words):
                word_found = False
                is_last_word = (i == len(input_words) - 1)
                
                for option_word in option_words:
                    if input_word == option_word:  # Exact match
                        score += 2
                        word_found = True
                        break
                    elif is_last_word and option_word.startswith(input_word):  # Last word starts with
                        score += 2
                        word_found = True
                        break
                    elif input_word in option_word:  # Partial match
                        score += 1
                        word_found = True
                
                # If input word not found in any option word, skip this option
                if not word_found:
                    score = 0
                    break
            
            if score > 0:
                suggestions[option] = score
        
        return suggestions
    
    def update_options(self, new_options):
        """Update options and refresh completer"""
        self.options = new_options
        self._setup_completer()
    
    def refresh_options(self):
        """Refresh options if they are callable (for dynamic database updates)"""
        if callable(self.options):
            self._setup_completer()
    
    def _update_autocomplete(self, text):
        """Update completer model and border styling based on input"""
        options_list = self._get_options_list()
        if not options_list or self.suggestions_frozen:
            return

        suggestions = self._calculate_suggestions(text)        # Sort suggestions by score (highest first)
        sorted_suggestions = sorted(suggestions.keys(), key=lambda x: suggestions[x], reverse=True)
        
        # Update completer model with sorted suggestions
        if self.completer:
            model = QStringListModel(sorted_suggestions)
            self.completer.setModel(model)
            # Set empty completion prefix to show all our pre-filtered results
            self.completer.setCompletionPrefix("")
        
        # Apply orange border if no matches found for non-empty input, preserve background
        if text.strip() and not suggestions:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; border: 2px solid orange; }")
        else:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; }")
    
    def _handle_edit_finished(self):
        """Handle completion of text editing"""
        self.suggestions_frozen = False
        text = self.text().strip()
        if text and self.options:
            suggestions = self._calculate_suggestions(text)
            if not suggestions:
                self.on_invalid_input(text)
    
    def on_invalid_input(self, text):
        """Override this method to handle invalid input cases"""
        pass


class AutoCompleteDelegate(QStyledItemDelegate):
    """Custom delegate for autocomplete editing in table cells"""
    
    def __init__(self, table_widget, parent=None):
        super().__init__(parent)
        self.table_widget = table_widget
    
    def createEditor(self, parent, option, index):
        """Create autocomplete editor for cell"""
        row, col = index.row(), index.column()
        options = self.table_widget.get_cell_options(row, col)
        
        editor = AutoCompleteLineEdit(parent, options)
        return editor
    
    def setEditorData(self, editor, index):
        """Set current cell value in editor"""
        value = index.model().data(index, Qt.EditRole)
        if value:
            editor.setText(str(value))
    
    def setModelData(self, editor, model, index):
        """Set editor value back to model"""
        model.setData(index, editor.text(), Qt.EditRole)


class AutoCompleteTableWidget(QTableWidget):
    """Table widget with autocomplete functionality for cells"""
    
    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        
        # Storage for cell and column options
        self.cell_options = {}  # {(row, col): [options]}
        self.column_options = {}  # {col: [options]}
        self.row_options = {}  # {row: [options]}
        
        # Set custom delegate for autocomplete editing
        self.delegate = AutoCompleteDelegate(self)
        self.setItemDelegate(self.delegate)
    
    def set_cell_options(self, row, col, options_list):
        """Set autocomplete options for specific cell"""
        self.cell_options[(row, col)] = options_list
    
    def set_column_options(self, col, options_list):
        """Set autocomplete options for entire column"""
        self.column_options[col] = options_list
    
    def set_row_options(self, row, options_list):
        """Set autocomplete options for entire row"""
        self.row_options[row] = options_list
    
    def get_cell_options(self, row, col):
        """Get autocomplete options for cell (priority: cell > column > row > empty)"""
        # Check specific cell first
        if (row, col) in self.cell_options:
            return self.cell_options[(row, col)]
        
        # Check column options
        if col in self.column_options:
            return self.column_options[col]
        
        # Check row options
        if row in self.row_options:
            return self.row_options[row]
        
        # No options available
        return []


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Demo setup
    window = QWidget()
    layout = QVBoxLayout(window)
    
    # Create table with autocomplete
    table = AutoCompleteTableWidget(4, 3)
    table.setHorizontalHeaderLabels(["Material", "Color", "Size"])
    
    # Set column options (all cells in column will use these)
    table.set_column_options(0, [  # Material column
        "wood", "metal", "plastic", "glass", "ceramic",
        "wooden table", "metal chair", "plastic box"
    ])
    
    table.set_column_options(1, [  # Color column
        "white", "black", "brown", "red", "blue", "green",
        "dark brown", "light blue", "bright red"
    ])
    
    table.set_column_options(2, [  # Size column
        "small", "medium", "large", "extra large",
        "very small", "medium size", "large box"
    ])
    
    # Set specific cell options (overrides column options)
    table.set_cell_options(0, 0, [  # First cell special options
        "premium wood", "exotic wood", "hardwood",
        "softwood", "wooden premium", "wood premium"
    ])
    
    # Set row options (for demonstration)
    table.set_row_options(3, [  # Last row special options
        "custom option", "special item", "unique choice",
        "custom special", "special custom"
    ])
    
    # Add some sample data
    sample_data = [
        ["wood", "brown", "large"],
        ["metal", "black", "small"],
        ["plastic", "white", "medium"],
        ["", "", ""]  # Empty row for testing
    ]
    
    for row, row_data in enumerate(sample_data):
        for col, value in enumerate(row_data):
            if value:
                item = QTableWidgetItem(value)
                table.setItem(row, col, item)
    
    # Demo UI
    layout.addWidget(QLabel("AutoComplete Table Demo"))
    layout.addWidget(QLabel("• Double-click cells to edit with autocomplete"))
    layout.addWidget(QLabel("• Material column: try 'wood' or 'metal'"))
    layout.addWidget(QLabel("• Color column: try 'dar' → 'dark brown'"))
    layout.addWidget(QLabel("• First cell has special options: try 'premium'"))
    layout.addWidget(QLabel("• Last row has custom options: try 'custom'"))
    layout.addWidget(table)
    
    # Add a regular lineedit for comparison
    comparison_layout = QHBoxLayout()
    comparison_layout.addWidget(QLabel("Compare with LineEdit:"))
    line_edit = AutoCompleteLineEdit()
    line_edit.options = ["wood", "metal", "wooden table", "metal chair"]
    line_edit._setup_completer()
    comparison_layout.addWidget(line_edit)
    layout.addLayout(comparison_layout)
    
    window.setWindowTitle("AutoComplete Table Demo")
    window.resize(600, 400)
    window.show()
    
    sys.exit(app.exec())