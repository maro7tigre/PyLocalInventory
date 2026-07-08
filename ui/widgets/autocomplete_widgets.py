import sys
from PySide6.QtWidgets import (QApplication, QLineEdit, QCompleter, QVBoxLayout, 
                               QWidget, QLabel, QTableWidget, QStyledItemDelegate, 
                               QTableWidgetItem, QHBoxLayout)
from PySide6.QtCore import Qt, QStringListModel, QTimer


class AutoCompleteLineEdit(QLineEdit):
    """Custom QLineEdit with smart autocomplete functionality"""

    TOKEN_SEPARATORS = {" ", ",", ";", "\n"}
    
    def __init__(self, parent=None, options=None, complete_multiple=False):
        super().__init__(parent)
        self.options = options or []
        self.completer = None
        self.suggestions_frozen = False
        self.complete_multiple = complete_multiple
        self._completion_base_text = ""
        self._completion_base_cursor = 0
        self._setting_multi_text = False
        
        # Set default background for table editing
        self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; }")
        
        # Connect signals for autocomplete functionality
        self.textChanged.connect(self._update_autocomplete)
        self.editingFinished.connect(self._handle_edit_finished)
        self._setup_completer()

    def keyPressEvent(self, event):
        """Handle arrow keys to freeze suggestions"""
        if self.complete_multiple and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.completer and self.completer.popup().isVisible():
                super().keyPressEvent(event)
                return
            self._insert_separator()
            event.accept()
            return

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
            self.setCompleter(self.completer)
    
    def _on_completion_selected(self, text):
        """Handle when user selects from completion dropdown"""
        if self.complete_multiple:
            self._replace_current_token(text)
        else:
            self.setText(text)
        # Hide the completer popup first
        if self.completer:
            self.completer.popup().hide()
        if not self.complete_multiple:
            QTimer.singleShot(0, self.clearFocus)

    def _current_token_span(self, text=None, cursor_pos=None):
        text = self.text() if text is None else str(text or "")
        cursor_pos = self.cursorPosition() if cursor_pos is None else cursor_pos
        cursor_pos = max(0, min(cursor_pos, len(text)))

        start = cursor_pos - 1
        while start >= 0 and text[start] not in self.TOKEN_SEPARATORS:
            start -= 1
        start += 1

        end = cursor_pos
        while end < len(text) and text[end] not in self.TOKEN_SEPARATORS:
            end += 1

        return start, end, text[start:cursor_pos]

    def _tokens_outside_span(self, text, start, end):
        other_text = f"{text[:start]} {text[end:]}"
        tokens = []
        token = []
        for char in other_text:
            if char in self.TOKEN_SEPARATORS:
                if token:
                    tokens.append("".join(token))
                    token = []
            else:
                token.append(char)
        if token:
            tokens.append("".join(token))
        return {item.strip().lower() for item in tokens if item.strip()}

    def _replace_current_token(self, suggestion):
        suggestion = str(suggestion or "").strip()
        if not suggestion:
            return

        text = self.text()
        cursor = self.cursorPosition()
        if (
            self._completion_base_text
            and text.strip().lower() == suggestion.lower()
            and text != self._completion_base_text
        ):
            text = self._completion_base_text
            cursor = self._completion_base_cursor

        start, end, _ = self._current_token_span(text, cursor)
        existing = self._tokens_outside_span(text, start, end)
        if suggestion.lower() in existing:
            new_text = text[:start] + text[end:]
            new_cursor = start
        else:
            new_text = text[:start] + suggestion + text[end:]
            new_cursor = start + len(suggestion)

        self._setting_multi_text = True
        super().setText(new_text)
        self._setting_multi_text = False
        self.setCursorPosition(new_cursor)
        self.setFocus()

    def _insert_separator(self):
        text = self.text()
        cursor = self.cursorPosition()
        if cursor > 0 and text[cursor - 1] not in self.TOKEN_SEPARATORS:
            insert_text = ", "
        else:
            insert_text = ""
        if not insert_text:
            return
        new_text = text[:cursor] + insert_text + text[cursor:]
        self._setting_multi_text = True
        super().setText(new_text)
        self._setting_multi_text = False
        self.setCursorPosition(cursor + len(insert_text))

    def _score_suggestions(self, query):
        options_list = self._get_options_list()
        if not query.strip():
            return {option: 1 for option in options_list}

        input_words = query.lower().split()
        suggestions = {}

        for option in options_list:
            option_words = option.lower().split()
            score = 0

            # Check if option starts with full input string
            if option.lower().startswith(query.lower()):
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

    def _calculate_suggestions(self, text):
        """Calculate suggestions with scoring system"""
        if self.complete_multiple:
            start, end, current_token = self._current_token_span(text, self.cursorPosition())
            if not current_token.strip():
                return {}
            suggestions = self._score_suggestions(current_token)
            existing = self._tokens_outside_span(str(text or ""), start, end)
            suggestions = {
                option: score
                for option, score in suggestions.items()
                if option.lower() not in existing
            }
        else:
            suggestions = self._score_suggestions(text)
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
        if not options_list or self.suggestions_frozen or self._setting_multi_text:
            return

        if not self.complete_multiple or not self._is_single_option_text(text, options_list):
            self._completion_base_text = text
            self._completion_base_cursor = self.cursorPosition()
        suggestions = self._calculate_suggestions(text)        # Sort suggestions by score (highest first)
        sorted_suggestions = sorted(suggestions.keys(), key=lambda x: suggestions[x], reverse=True)
        
        # Update completer model with sorted suggestions
        if self.completer:
            model = QStringListModel(sorted_suggestions)
            self.completer.setModel(model)
            # Set empty completion prefix to show all our pre-filtered results
            self.completer.setCompletionPrefix("")
            if self.complete_multiple and sorted_suggestions and self.hasFocus():
                self.completer.complete()
        
        # Apply orange border if no matches found for non-empty input, preserve background
        has_query = bool(str(text or "").strip())
        if self.complete_multiple:
            _, _, current_token = self._current_token_span(text, self.cursorPosition())
            has_query = bool(current_token.strip())
        if has_query and not suggestions:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; border: 2px solid orange; }")
        else:
            self.setStyleSheet("QLineEdit { background-color: #2D2D2D; color: white; }")

    def _is_single_option_text(self, text, options_list):
        value = str(text or "").strip().lower()
        if not value:
            return False
        return (
            value in {str(option).strip().lower() for option in options_list}
            and not any(separator in str(text or "") for separator in self.TOKEN_SEPARATORS)
        )
    
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
