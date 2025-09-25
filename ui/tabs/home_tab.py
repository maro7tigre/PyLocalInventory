"""
Home tab - Beautiful dashboard with charts, statistics, and quick actions
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QFrame, QScrollArea, QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter, QPen, QBrush, QColor, QLinearGradient
from PySide6.QtCharts import QChart, QChartView, QPieSeries, QBarSeries, QBarSet, QLineSeries, QValueAxis, QBarCategoryAxis
from datetime import datetime, timedelta
import sqlite3

from ui.widgets.themed_widgets import GreenButton, BlueButton, OrangeButton, RedButton

class StatCard(QFrame):
    """Beautiful statistic card widget"""
    def __init__(self, title, value, subtitle="", color="#4CAF50", parent=None):
        super().__init__(parent)
        self.title = title
        self.value = value
        self.subtitle = subtitle
        self.color = color
        self.setup_ui()
    
    def setup_ui(self):
        self.setFixedHeight(120)
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3c3c3c, stop:1 #2b2b2b);
                border: 2px solid {self.color};
                border-radius: 12px;
                padding: 16px;
            }}
            QFrame:hover {{
                border-color: #ffffff;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #4a4a4a, stop:1 #3c3c3c);
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        
        # Title
        title_label = QLabel(self.title)
        title_label.setStyleSheet(f"color: {self.color}; font-size: 12px; font-weight: bold;")
        layout.addWidget(title_label)
        
        # Value
        value_label = QLabel(str(self.value))
        value_label.setStyleSheet("color: #ffffff; font-size: 28px; font-weight: bold;")
        layout.addWidget(value_label)
        
        # Subtitle
        if self.subtitle:
            subtitle_label = QLabel(self.subtitle)
            subtitle_label.setStyleSheet("color: #cccccc; font-size: 10px;")
            layout.addWidget(subtitle_label)
        
        layout.addStretch()
    
    def update_value(self, value, subtitle=""):
        """Update the card value and subtitle"""
        self.value = value
        self.subtitle = subtitle
        # Find and update the value label
        for i in range(self.layout().count()):
            widget = self.layout().itemAt(i).widget()
            if widget and isinstance(widget, QLabel):
                if "font-size: 28px" in widget.styleSheet():
                    widget.setText(str(value))
                elif "font-size: 10px" in widget.styleSheet() and subtitle:
                    widget.setText(subtitle)

class QuickActionCard(QFrame):
    """Beautiful quick action card"""
    clicked = Signal(str)  # Emit the action type
    
    def __init__(self, title, subtitle, action_type, icon_text="", color="#2196F3", parent=None):
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.action_type = action_type
        self.icon_text = icon_text
        self.color = color
        self.setup_ui()
    
    def setup_ui(self):
        self.setFixedHeight(100)
        self.setCursor(Qt.PointingHandCursor)
        # Apply style only to this card widget, not its children
        self.setObjectName("quickActionCard")
        self.setStyleSheet(
            f"#quickActionCard {{"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3c3c3c, stop:1 #2b2b2b);"
            f" border: 2px solid {self.color};"
            f" border-radius: 12px;"
            f" padding: 12px;"
            f"}}"
            f"#quickActionCard:hover {{"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.color}, stop:1 #2b2b2b);"
            f" border-color: #ffffff;"
            f"}}"
        )
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        # Icon
        if self.icon_text:
            icon_label = QLabel(self.icon_text)
            # Local style for the emoji preview only
            icon_label.setStyleSheet(f"color: {self.color}; font-size: 32px; font-weight: bold;")
            icon_label.setFixedWidth(56)
            icon_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon_label)
        
        # Text content
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        title_label = QLabel(self.title)
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        text_layout.addWidget(title_label)
        
        subtitle_label = QLabel(self.subtitle)
        text_layout.addWidget(subtitle_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        # Arrow indicator
        arrow_label = QLabel("→")
        arrow_font = arrow_label.font()
        arrow_font.setPointSize(20)
        arrow_font.setBold(True)
        arrow_label.setFont(arrow_font)
        layout.addWidget(arrow_label)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.action_type)
        super().mousePressEvent(event)

class HomeTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.stat_cards = {}
        self.charts = {}
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_statistics)
        self.refresh_timer.start(30000)  # Refresh every 30 seconds
        self.setup_ui()
        self.refresh_statistics()
    
    def setup_ui(self):
        """Setup the beautiful home dashboard interface"""
        # Create scroll area for the entire content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2b2b2b;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777777;
            }
        """)
        
        # Main content widget
        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(24, 24, 24, 24)
        
    # Header section (removed per request)
    # Statistics cards section (removed per request)
        
        # Charts section
        self.create_charts_section(main_layout)
        
        # Quick actions section
        self.create_quick_actions_section(main_layout)
        
        # Recent activity section
        self.create_recent_activity_section(main_layout)
        
        scroll_area.setWidget(content_widget)
        
        # Set the scroll area as the main layout
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll_area)
    
    def create_header_section(self, parent_layout):
        """Create the header section with welcome message"""
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:1 #2196F3);
                border-radius: 16px;
                padding: 20px;
            }
        """)
        header_frame.setFixedHeight(100)
        
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(24, 16, 24, 16)
        
        # Welcome message
        welcome_label = QLabel("📊 Dashboard Overview")
        welcome_label.setStyleSheet("color: #ffffff; font-size: 24px; font-weight: bold;")
        header_layout.addWidget(welcome_label)
        
        # Current date and database status
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        db_status = "🟢 Connected" if self.database and self.database.conn else "🔴 Disconnected"
        status_label = QLabel(f"Today: {current_date} • Database: {db_status}")
        status_label.setStyleSheet("color: #ffffff; font-size: 12px; opacity: 0.9;")
        header_layout.addWidget(status_label)
        
        parent_layout.addWidget(header_frame)
    
    def create_statistics_section(self, parent_layout):
        """Create the statistics cards section"""
        stats_label = QLabel("📈 Key Metrics")
        stats_label.setStyleSheet("""
            QLabel {
                color: #ffffff; 
                font-size: 18px; 
                font-weight: bold; 
                margin-bottom: 12px;
                background: transparent;
            }
        """)
        parent_layout.addWidget(stats_label)
        
        # Statistics grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(16)
        
        # Create stat cards
        self.stat_cards['total_sales'] = StatCard("Total Sales", "0", "This month", "#4CAF50")
        self.stat_cards['total_imports'] = StatCard("Total Imports", "0", "This month", "#2196F3")
        self.stat_cards['products_count'] = StatCard("Products", "0", "In inventory", "#FF9800")
        self.stat_cards['low_stock'] = StatCard("Low Stock", "0", "Items below 5", "#f44336")
        self.stat_cards['clients_count'] = StatCard("Clients", "0", "Active clients", "#9C27B0")
        self.stat_cards['suppliers_count'] = StatCard("Suppliers", "0", "Active suppliers", "#607D8B")
        
        # Add cards to grid (3 columns)
        row, col = 0, 0
        for card in self.stat_cards.values():
            stats_grid.addWidget(card, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        parent_layout.addLayout(stats_grid)
    
    def create_charts_section(self, parent_layout):
        """Create the charts section"""
        charts_label = QLabel("📊 Visual Analytics")
        charts_label.setStyleSheet("""
            QLabel {
                color: #ffffff; 
                font-size: 18px; 
                font-weight: bold; 
                margin-bottom: 12px;
                background: transparent;
            }
        """)
        parent_layout.addWidget(charts_label)
        
        charts_container = QHBoxLayout()
        charts_container.setSpacing(16)
        
        # Sales vs Imports chart (Bar chart with profit line)
        self.create_monthly_comparison_chart(charts_container)
        
        # Low stock products list
        self.create_low_stock_section(charts_container)
        
        parent_layout.addLayout(charts_container)
    
    def create_monthly_comparison_chart(self, parent_layout):
        """Create monthly sales vs imports comparison chart with profit line"""
        chart = QChart()
        chart.setTitle("Monthly Financial Overview")
        chart.setTitleBrush(QBrush(QColor("#ffffff")))
        try:
            title_font = QFont()
            title_font.setBold(True)
            chart.setTitleFont(title_font)
        except Exception:
            pass
        chart.setBackgroundBrush(QBrush(QColor("#3c3c3c")))
        chart.legend().setLabelColor(QColor("#ffffff"))
        
        # Create bar series
        bar_series = QBarSeries()
        
        sales_set = QBarSet("Sales")
        imports_set = QBarSet("Imports (Cost)")
        
        # Create line series for profit
        profit_series = QLineSeries()
        profit_series.setName("Profit")
        
        # Get last 6 months data
        months = []
        sales_data = []
        imports_data = []
        profit_data = []
        
        for i in range(5, -1, -1):
            date = datetime.now() - timedelta(days=i*30)
            month_name = date.strftime("%b")
            months.append(month_name)
            
            # Get sales and imports for this month
            sales_total = self.get_monthly_total('Sales', date.year, date.month)
            imports_total = self.get_monthly_total('Imports', date.year, date.month)
            profit = sales_total - imports_total
            
            sales_data.append(sales_total)
            imports_data.append(-imports_total)  # Make imports negative (costs)
            profit_data.append(profit)
            
            # Add point to line series
            profit_series.append(5-i, profit)
        
        sales_set.append(sales_data)
        imports_set.append(imports_data)
        
        # Set colors
        sales_set.setColor(QColor("#4CAF50"))  # Green for income
        imports_set.setColor(QColor("#f44336"))  # Red for costs (negative)
        
        bar_series.append(sales_set)
        bar_series.append(imports_set)
        
        # Add both series to chart
        chart.addSeries(bar_series)
        chart.addSeries(profit_series)
        
        # Style profit line
        pen = profit_series.pen()
        pen.setColor(QColor("#2196F3"))
        pen.setWidth(3)
        profit_series.setPen(pen)
        
        # Create axes
        categories_axis = QBarCategoryAxis()
        categories_axis.append(months)
        categories_axis.setLabelsColor(QColor("#ffffff"))
        chart.addAxis(categories_axis, Qt.AlignBottom)
        bar_series.attachAxis(categories_axis)
        
        value_axis = QValueAxis()
        value_axis.setLabelsColor(QColor("#ffffff"))
        chart.addAxis(value_axis, Qt.AlignLeft)
        bar_series.attachAxis(value_axis)
        profit_series.attachAxis(value_axis)
        
        # Add a bold white zero baseline line across the chart
        try:
            zero_series = QLineSeries()
            zero_series.setName("")
            # Extend slightly before first and after last category to reach edges
            zero_series.append(-0.5, 0)
            zero_series.append(len(months) - 0.5, 0)
            zero_pen = zero_series.pen()
            zero_pen.setColor(QColor("#FFFFFF"))
            zero_pen.setWidth(4)
            try:
                zero_pen.setCapStyle(Qt.FlatCap)
            except Exception:
                pass
            zero_series.setPen(zero_pen)
            chart.addSeries(zero_series)
            zero_series.attachAxis(categories_axis)
            zero_series.attachAxis(value_axis)
            try:
                for m in chart.legend().markers(zero_series):
                    m.setVisible(False)
            except Exception:
                pass
        except Exception:
            pass

        # Create chart view
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.Antialiasing)
        chart_view.setMinimumHeight(300)
        chart_view.setStyleSheet("background-color: transparent; border: 2px solid #555555; border-radius: 8px;")
        
        self.charts['monthly_comparison'] = chart_view
        parent_layout.addWidget(chart_view)
    
    def create_low_stock_section(self, parent_layout):
        """Create low stock products section with ordered list"""
        # Simplified container to avoid widget-in-widget styling layers
        container = QWidget()
        container.setObjectName("lowStockContainer")
        container.setStyleSheet(
            "#lowStockContainer { border: 1px solid #555555; border-radius: 8px; background: transparent; padding: 16px; }"
        )
        container.setMinimumHeight(300)
        container.setMaximumWidth(400)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        
        # Title
        title_label = QLabel("📦 Low Stock Alert")
        title_label.setStyleSheet("""
            QLabel {
                color: #f44336;
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 8px;
                background: transparent;
            }
        """)
        layout.addWidget(title_label)
        
        # Threshold info
        threshold = 5  # You can adjust this later
        info_label = QLabel(f"Products with stock ≤ {threshold}:")
        info_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 12px;
                margin-bottom: 8px;
                background: transparent;
            }
        """)
        layout.addWidget(info_label)
        
        # Scroll area for products list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        # Products list widget
        products_widget = QWidget()
        products_layout = QVBoxLayout(products_widget)
        products_layout.setContentsMargins(0, 0, 0, 0)
        products_layout.setSpacing(6)
        
        # Get low stock products
        low_stock_products = self.get_low_stock_products(threshold)
        
        if not low_stock_products:
            no_issues = QLabel("✅ All products have sufficient stock")
            no_issues.setStyleSheet("color: #4CAF50; font-size: 12px; padding: 8px;")
            no_issues.setAlignment(Qt.AlignCenter)
            products_layout.addWidget(no_issues)
        else:
            for product in low_stock_products:
                product_item = self.create_low_stock_item(product)
                products_layout.addWidget(product_item)
        
        products_layout.addStretch()
        scroll_area.setWidget(products_widget)
        layout.addWidget(scroll_area)
        
        parent_layout.addWidget(container)
    
    def create_quick_actions_section(self, parent_layout):
        """Create quick action buttons section"""
        actions_label = QLabel("⚡ Quick Actions")
        actions_label.setStyleSheet("""
            QLabel {
                color: #ffffff; 
                font-size: 18px; 
                font-weight: bold; 
                margin-bottom: 12px;
                background: transparent;
            }
        """)
        parent_layout.addWidget(actions_label)
        
        actions_container = QGridLayout()
        actions_container.setSpacing(16)
        
        # Create quick action cards
        actions = [
            ("New Sale", "Record a new sales transaction", "new_sale", "💰", "#4CAF50"),
            ("New Import", "Add new import operation", "new_import", "📥", "#2196F3"),
            ("View Sales", "Switch to sales management", "view_sales", "🛒", "#FF9800"),
            ("View Imports", "Switch to imports management", "view_imports", "📦", "#9C27B0")
        ]
        
        row, col = 0, 0
        for title, subtitle, action_type, icon, color in actions:
            card = QuickActionCard(title, subtitle, action_type, icon, color)
            card.clicked.connect(self.handle_quick_action)
            actions_container.addWidget(card, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1
        
        parent_layout.addLayout(actions_container)
    
    def create_recent_activity_section(self, parent_layout):
        """Create recent activity section"""
        activity_label = QLabel("🕒 Recent Activity")
        activity_label.setStyleSheet("""
            QLabel {
                color: #ffffff; 
                font-size: 18px; 
                font-weight: bold; 
                margin-bottom: 12px;
                background: transparent;
            }
        """)
        parent_layout.addWidget(activity_label)
        
        # Activity container
        activity_frame = QFrame()
        activity_frame.setStyleSheet("""
            QFrame {
                background-color: #3c3c3c;
                border: 2px solid #555555;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        activity_frame.setFixedHeight(200)
        
        activity_layout = QVBoxLayout(activity_frame)
        
        # Recent transactions
        recent_activities = self.get_recent_activities()
        
        if not recent_activities:
            no_activity = QLabel("No recent activity")
            no_activity.setStyleSheet("color: #888888; font-size: 14px; text-align: center;")
            no_activity.setAlignment(Qt.AlignCenter)
            activity_layout.addWidget(no_activity)
        else:
            for activity in recent_activities[:5]:  # Show last 5 activities
                activity_widget = self.create_activity_item(activity)
                activity_layout.addWidget(activity_widget)
        
        activity_layout.addStretch()
        parent_layout.addWidget(activity_frame)
    
    def create_activity_item(self, activity):
        """Create a single activity item widget"""
        item_frame = QFrame()
        item_frame.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px;
                margin: 2px;
            }
        """)
        
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(12, 8, 12, 8)
        
        # Activity type icon
        icon = "💰" if activity['type'] == 'Sales' else "📥"
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 16px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)
        
        # Description
        desc_label = QLabel(activity['description'])
        desc_label.setStyleSheet("color: #ffffff; font-size: 12px;")
        item_layout.addWidget(desc_label)
        
        item_layout.addStretch()
        
        # Amount
        amount_label = QLabel(f"{activity['amount']:.2f} MAD")
        amount_color = "#4CAF50" if activity['type'] == 'Sales' else "#2196F3"
        amount_label.setStyleSheet(f"color: {amount_color}; font-size: 12px; font-weight: bold;")
        item_layout.addWidget(amount_label)
        
        return item_frame
    
    def refresh_statistics(self):
        """Refresh all statistics and charts"""
        if not self.database or not self.database.conn:
            return
        
        try:
            # Update stat cards
            current_month = datetime.now().month
            current_year = datetime.now().year
            
            # Total sales this month
            sales_total = self.get_monthly_total('Sales', current_year, current_month)
            if 'total_sales' in self.stat_cards:
                self.stat_cards['total_sales'].update_value(f"{sales_total:.0f} MAD", "This month")
            
            # Total imports this month
            imports_total = self.get_monthly_total('Imports', current_year, current_month)
            if 'total_imports' in self.stat_cards:
                self.stat_cards['total_imports'].update_value(f"{imports_total:.0f} MAD", "This month")
            
            # Products count
            products_count = self.get_table_count('Products')
            if 'products_count' in self.stat_cards:
                self.stat_cards['products_count'].update_value(products_count, "In inventory")
            
            # Low stock items
            low_stock_count = self.get_low_stock_count()
            if 'low_stock' in self.stat_cards:
                self.stat_cards['low_stock'].update_value(low_stock_count, "Items below 5")
            
            # Clients count
            clients_count = self.get_table_count('Clients')
            if 'clients_count' in self.stat_cards:
                self.stat_cards['clients_count'].update_value(clients_count, "Active clients")
            
            # Suppliers count
            suppliers_count = self.get_table_count('Suppliers')
            if 'suppliers_count' in self.stat_cards:
                self.stat_cards['suppliers_count'].update_value(suppliers_count, "Active suppliers")
            
            print("✓ Dashboard statistics refreshed")
            
        except Exception as e:
            print(f"Error refreshing statistics: {e}")
    
    def get_monthly_total(self, table_name, year, month):
        """Get total amount for a specific month"""
        if not self.database or not self.database.cursor:
            return 0.0
        
        try:
            if table_name == 'Sales':
                # Calculate total from Sales_Items for sales in this month
                query = """
                    SELECT COALESCE(SUM(si.quantity * si.unit_price * (1 + s.tva/100)), 0)
                    FROM Sales s
                    JOIN Sales_Items si ON s.ID = si.sales_id
                    WHERE strftime('%Y', s.date) = ? AND strftime('%m', s.date) = ?
                """
            elif table_name == 'Imports':
                # Calculate total from Import_Items for imports in this month
                query = """
                    SELECT COALESCE(SUM(ii.quantity * ii.unit_price * (1 + i.tva/100)), 0)
                    FROM Imports i
                    JOIN Import_Items ii ON i.ID = ii.import_id
                    WHERE strftime('%Y', i.date) = ? AND strftime('%m', i.date) = ?
                """
            else:
                return 0.0
            
            self.database.cursor.execute(query, (str(year), f"{month:02d}"))
            result = self.database.cursor.fetchone()
            return float(result[0]) if result else 0.0
        except Exception as e:
            print(f"Error getting monthly total for {table_name}: {e}")
            return 0.0
    
    def get_table_count(self, table_name):
        """Get count of records in a table"""
        if not self.database or not self.database.cursor:
            return 0
        
        try:
            self.database.cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            result = self.database.cursor.fetchone()
            return int(result[0]) if result else 0
        except Exception as e:
            print(f"Error getting count for {table_name}: {e}")
            return 0
    
    def get_low_stock_count(self):
        """Get count of products with stock below 5"""
        if not self.database or not self.database.cursor:
            return 0
        
        try:
            # This is a simplified version - in reality you'd calculate based on imports/sales
            query = """
                SELECT COUNT(*) FROM Products p
                WHERE (
                    SELECT COALESCE(SUM(ii.quantity), 0) - COALESCE(SUM(si.quantity), 0)
                    FROM Import_Items ii
                    LEFT JOIN Sales_Items si ON ii.product_id = si.product_id
                    WHERE ii.product_id = p.ID
                ) < 5
            """
            self.database.cursor.execute(query)
            result = self.database.cursor.fetchone()
            return int(result[0]) if result else 0
        except Exception as e:
            print(f"Error getting low stock count: {e}")
            return 0
    
    def get_low_stock_products(self, threshold=5):
        """Get products with stock below threshold, ordered by quantity (lowest first)"""
        if not self.database or not self.database.cursor:
            return []
        
        try:
            query = """
                SELECT p.name, p.username,
                    (COALESCE(
                        (SELECT SUM(ii.quantity) FROM Import_Items ii WHERE ii.product_id = p.ID), 0
                    ) - COALESCE(
                        (SELECT SUM(si.quantity) FROM Sales_Items si WHERE si.product_id = p.ID), 0
                    )) as stock_level
                FROM Products p
                WHERE (COALESCE(
                        (SELECT SUM(ii.quantity) FROM Import_Items ii WHERE ii.product_id = p.ID), 0
                    ) - COALESCE(
                        (SELECT SUM(si.quantity) FROM Sales_Items si WHERE si.product_id = p.ID), 0
                    )) <= ?
                ORDER BY stock_level ASC, p.name ASC
                LIMIT 15
            """
            self.database.cursor.execute(query, (threshold,))
            results = self.database.cursor.fetchall()
            
            products = []
            for name, username, stock_level in results:
                products.append({
                    'name': name or username or 'Unknown Product',
                    'username': username or '',
                    'stock': int(stock_level)
                })
            
            return products
            
        except Exception as e:
            print(f"Error getting low stock products: {e}")
            return []
    
    def create_low_stock_item(self, product):
        """Create a single low stock product item"""
        # Simplified row (no nested frames/backgrounds)
        item_widget = QWidget()
        layout = QHBoxLayout(item_widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        
        # Product name
        name_label = QLabel(product['name'])
        layout.addWidget(name_label)
        
        layout.addStretch()
        
        # Stock quantity with warning color
        stock = product['stock']
        if stock <= 0:
            stock_color = "#f44336"  # Red for out of stock
            stock_text = "OUT"
        elif stock <= 2:
            stock_color = "#FF5722"  # Dark orange for critical
            stock_text = str(stock)
        else:
            stock_color = "#FF9800"  # Orange for low
            stock_text = str(stock)
        
        stock_label = QLabel(stock_text)
        stock_label.setStyleSheet(f"color: {stock_color}; font-weight: bold; min-width: 30px;")
        stock_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(stock_label)
        
        return item_widget
    
    def get_recent_activities(self):
        """Get recent sales and import activities"""
        activities = []
        
        if not self.database or not self.database.cursor:
            return activities
        
        try:
            # Get recent sales with calculated totals
            sales_query = """
                SELECT 'Sales' as type, s.date, 
                    COALESCE(SUM(si.quantity * si.unit_price * (1 + s.tva/100)), 0) as total,
                    'Sale to ' || s.client_username as description
                FROM Sales s
                LEFT JOIN Sales_Items si ON s.ID = si.sales_id
                GROUP BY s.ID, s.date, s.client_username, s.tva
                ORDER BY s.date DESC, s.ID DESC 
                LIMIT 5
            """
            self.database.cursor.execute(sales_query)
            sales_results = self.database.cursor.fetchall()
            
            for result in sales_results:
                activities.append({
                    'type': result[0],
                    'date': result[1],
                    'amount': float(result[2]),
                    'description': result[3]
                })
            
            # Get recent imports with calculated totals
            imports_query = """
                SELECT 'Imports' as type, i.date,
                    COALESCE(SUM(ii.quantity * ii.unit_price * (1 + i.tva/100)), 0) as total,
                    'Import from ' || i.supplier_username as description
                FROM Imports i
                LEFT JOIN Import_Items ii ON i.ID = ii.import_id
                GROUP BY i.ID, i.date, i.supplier_username, i.tva
                ORDER BY i.date DESC, i.ID DESC 
                LIMIT 5
            """
            self.database.cursor.execute(imports_query)
            imports_results = self.database.cursor.fetchall()
            
            for result in imports_results:
                activities.append({
                    'type': result[0],
                    'date': result[1],
                    'amount': float(result[2]),
                    'description': result[3]
                })
            
            # Sort all activities by date (most recent first)
            activities.sort(key=lambda x: x['date'], reverse=True)
            
            return activities[:10]  # Return top 10 most recent
            
        except Exception as e:
            print(f"Error getting recent activities: {e}")
            return activities
    
    def handle_quick_action(self, action_type):
        """Handle quick action button clicks"""
        print(f"Quick action triggered: {action_type}")
        
        # Get the main window (parent of parent tabs)
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'tab_widget'):
            main_window = main_window.parent()
        
        if not main_window or not hasattr(main_window, 'tab_widget'):
            print("Could not find main window")
            return
        
        tab_widget = main_window.tab_widget
        
        # Map actions to tab indices (adjust based on your tab order)
        action_tab_map = {
            'view_sales': 4,      # Sales tab
            'view_imports': 5,    # Imports tab  
            'manage_clients': 2,  # Clients tab
            'manage_suppliers': 3 # Suppliers tab
        }
        
        if action_type in action_tab_map:
            # Switch to the appropriate tab
            tab_widget.setCurrentIndex(action_tab_map[action_type])
        
        elif action_type == 'new_sale':
            # Switch to sales tab and trigger new sale dialog
            tab_widget.setCurrentIndex(4)
            # Trigger the add dialog on the sales tab (BaseTab API)
            sales_tab = tab_widget.widget(4)
            if hasattr(sales_tab, 'add_item'):
                sales_tab.add_item()
            else:
                try:
                    # Fallback: click the add button if exposed
                    if hasattr(sales_tab, 'add_btn'):
                        sales_tab.add_btn.click()
                except Exception:
                    pass
        
        elif action_type == 'new_import':
            # Switch to imports tab and trigger new import dialog
            tab_widget.setCurrentIndex(5)
            # Trigger the add dialog on the imports tab (BaseTab API)
            imports_tab = tab_widget.widget(5)
            if hasattr(imports_tab, 'add_item'):
                imports_tab.add_item()
            else:
                try:
                    if hasattr(imports_tab, 'add_btn'):
                        imports_tab.add_btn.click()
                except Exception:
                    pass
    
    def refresh_on_tab_switch(self):
        """Called when this tab becomes active - refresh all data"""
        self.refresh_statistics()
        print("✓ Home tab refreshed on switch")