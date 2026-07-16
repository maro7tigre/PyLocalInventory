import sys
from PySide6.QtWidgets import (QApplication, QLineEdit, QCompleter, QVBoxLayout, 
                               QWidget, QLabel, QTableWidget, QStyledItemDelegate, 
                               QTableWidgetItem, QHBoxLayout, QTextEdit)
from PySide6.QtCore import Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QTextCursor


class AutoCompleteLineEdit(QLineEdit):
    """Custom QLineEdit with smart autocomplete functionality"""
    
    def __init__(self, parent=None, options=None, allow_free_text=False, multi_value=False):
        super().__init__(parent)
        self.options = options or []
        self.allow_free_text = allow_free_text
        self.multi_value = multi_value
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
            self.completer.activated.connect(self._on_completion_selected)
            # Use highlighted signal for mouse clicks (more reliable than activated)
            self.completer.highlighted.connect(self._on_completion_highlighted)
            self.setCompleter(self.completer)
    
    def _on_completion_selected(self, text):
        """Handle when user selects from completion dropdown"""
        if self.multi_value:
            current = self.text()
            cursor = self.cursorPosition()
            prefix = current[:cursor]
            suffix = current[cursor:]

            # Replace only the word currently being typed. Everything else
            # (dimensions, notes, numbers, and earlier keywords) is preserved.
            token_start = cursor
            while token_start > 0 and prefix[token_start - 1] not in " ,;\n\t":
                token_start -= 1
            before = current[:token_start]
            separator = "" if not before or before[-1].isspace() else " "
            completed = f"{before}{separator}{text}"
            if not suffix.lstrip().startswith((",", ";")):
                completed += ", "
            completed += suffix.lstrip()
            self.setText(completed)
            self.setCursorPosition(len(completed) - len(suffix.lstrip()))
        else:
            self.setText(text)
        # Hide the completer popup first
        if self.completer:
            self.completer.popup().hide()
        # Then clear focus to commit the edit
        QTimer.singleShot(0, self.clearFocus)
    
    def _on_completion_highlighted(self, text):
        """Handle when user highlights an item in completion dropdown"""
        # Directly trigger selection when highlighted (this covers mouse clicks)
        self._on_completion_selected(text)
    
    def _calculate_suggestions(self, text):
        """Calculate suggestions with scoring system"""
        options_list = self._get_options_list()
        search_text = text
        if self.multi_value:
            cursor = self.cursorPosition()
            prefix = text[:cursor]
            token_start = len(prefix)
            while token_start > 0 and prefix[token_start - 1] not in " ,;\n\t":
                token_start -= 1
            search_text = prefix[token_start:]

        if not search_text.strip():
            return {option: 1 for option in options_list}
        
        input_words = search_text.lower().split()
        suggestions = {}
        
        for option in options_list:
            option_words = option.lower().split()
            score = 0
            
            # Check if option starts with full input string
            if option.lower().startswith(search_text.lower()):
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
        if text.strip() and not suggestions and not self.allow_free_text:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; border: 2px solid orange; }")
        else:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; }")
    
    def _handle_edit_finished(self):
        """Handle completion of text editing"""
        self.suggestions_frozen = False
        text = self.text().strip()
        if text and self.options and not self.allow_free_text:
            suggestions = self._calculate_suggestions(text)
            if not suggestions:
                self.on_invalid_input(text)
    
    def on_invalid_input(self, text):
        """Override this method to handle invalid input cases"""
        pass


class AutoExpandingTextEdit(QTextEdit):
    """Wrapping free-text editor that grows its containing table row."""

    editingFinished = Signal()

    def __init__(self, parent=None, options=None, minimum_height=56, maximum_height=160,
                 multi_value=False, allow_free_text=True):
        super().__init__(parent)
        self.options = options or []
        self.multi_value = multi_value
        self.allow_free_text = allow_free_text
        self.minimum_editor_height = minimum_height
        self.maximum_editor_height = maximum_height
        self.setAcceptRichText(False)
        self.setPlaceholderText("Information")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("QTextEdit { background-color: #2D2D2D; color: white; padding: 5px; }")

        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(5)
        self.completer.activated.connect(self._insert_completion)

        self.textChanged.connect(self._on_text_changed)
        self._refresh_completions()
        self._adjust_height()

    def text(self):
        """Provide the QLineEdit-compatible API used by operation tables."""
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(str(text or ""))

    def _get_options_list(self):
        if callable(self.options):
            try:
                return self.options() or []
            except Exception as exc:
                print(f"Error calling options method: {exc}")
                return []
        return self.options or []

    def _current_fragment(self):
        cursor = self.textCursor()
        text = self.toPlainText()
        position = cursor.position()
        start = position
        while start > 0 and text[start - 1] not in " ,;\n\t":
            start -= 1
        return text[start:position], start, position

    def _refresh_completions(self):
        fragment, _, _ = self._current_fragment()
        options = self._get_options_list()
        if not fragment.strip():
            matches = []
        else:
            needle = fragment.casefold()
            matches = [option for option in options if needle in str(option).casefold()]
        self.completer.setModel(QStringListModel(matches, self.completer))
        self.completer.setWidget(self)
        return matches

    def _on_text_changed(self):
        matches = self._refresh_completions()
        self._adjust_height()
        if matches and self.hasFocus():
            popup_rect = self.cursorRect()
            popup_rect.setWidth(max(220, self.completer.popup().sizeHintForColumn(0) + 24))
            self.completer.complete(popup_rect)
        else:
            self.completer.popup().hide()

    def _insert_completion(self, completion):
        if not self.multi_value:
            self.setPlainText(str(completion))
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
            self.completer.popup().hide()
            return

        _, start, end = self._current_fragment()
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.insertText(f"{completion}, ")
        self.setTextCursor(cursor)
        self.completer.popup().hide()

    def keyPressEvent(self, event):
        if self.completer.popup().isVisible() and event.key() in (
            Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Backtab,
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def _adjust_height(self):
        document_height = int(self.document().documentLayout().documentSize().height()) + 12
        desired = max(self.minimum_editor_height, min(self.maximum_editor_height, document_height))
        if self.minimumHeight() != desired or self.maximumHeight() != desired:
            self.setFixedHeight(desired)

        row = self.property('row')
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QTableWidget):
            parent = parent.parentWidget()
        if parent is not None and row is not None:
            row = int(row)
            editor_heights = [
                parent.cellWidget(row, column).height() + 2
                for column in range(parent.columnCount())
                if parent.cellWidget(row, column) is not None
                and isinstance(parent.cellWidget(row, column), AutoExpandingTextEdit)
            ]
            parent.setRowHeight(row, max([58, *editor_heights]))


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
