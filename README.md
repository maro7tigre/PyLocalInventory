# PyLocalInventory

# Inventory & Sales Desktop App - Project Specification

## Project Goal

Create a desktop application for inventory and sales management that runs locally on a single computer. The application should support multiple user profiles, each with separate databases and optional encryption. The app should be completely offline and portable, requiring no internet connection or external hosting.

## Technology Stack

- **Language:** Python
- **GUI Framework:** PySide6
- **Database:** SQLite (built into Python's standard library)
- **Theme:** Dark mode throughout the entire application
- **Encryption:** Optional application-level encryption (encrypt before writing, decrypt after reading)

## Key Features & Approach

### Database Strategy
- **SQLite over JSON:** Better for data relationships, querying, performance, and data integrity
- **Zero setup required:** SQLite is built into Python, no installation or configuration needed
- **Profile isolation:** Each profile gets its own separate database file
- **Portability:** Complete profile folders can be copied/moved between devices

### Profile Management
Each profile is stored as a separate folder containing:
```
profiles/
├── profile1/
│   ├── inventory.db
│   └── profile_config.json
└── profile2/
    ├── inventory.db
    └── profile_config.json
```

### Authentication System
- Password-protected profiles (optional)
- Password stored and validated through `core/password.py`
- Global password variable for session management
- Automatic logout functionality
- Password validation with visual feedback (red border on incorrect entry)

## Application Structure

### Main Window Layout
- **Menu Bar:** Access to profiles manager, backups manager, encryption password, and log out
- **Main Widget:** Dynamic content area that changes based on authentication state

### Authentication Flow
1. **Locked State:** Shows password input field with label and confirm button
2. **Password Validation:** 
   - Enter key or button press triggers validation
   - Incorrect password: red border on input field
   - Border resets to normal on content change
   - Correct password: switches to main application tabs
3. **Authenticated State:** Shows main application tabs (Home, Operations, Products, Clients, Suppliers, Log)

### Dialog System
Three main dialogs accessible from menu:
- Profiles Manager (with confirm/cancel options)
- Backups Manager (with confirm/cancel options) 
- Encryption Password (with confirm/cancel options)

## File Structure

```
project_root/
├── main.py                              # Application entry point
├── ui/
│   ├── main_window.py                   # Main window coordination
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── profiles_dialog.py           # Profile management dialog
│   │   ├── backups_dialog.py            # Backup management dialog
│   │   ├── encryption_dialog.py         # Encryption settings dialog
│   │   ├── product_dialog.py            # Product add/edit dialog
│   │   ├── client_dialog.py             # Client add/edit dialog
│   │   └── supplier_dialog.py           # Supplier add/edit dialog
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── themed_widgets.py            # Dark mode styled widgets
│   │   └── custom_widgets.py            # Reusable custom widgets
│   └── tabs/
│       ├── __init__.py
│       ├── home_tab.py                  # Dashboard/overview
│       ├── operations_tab.py            # Daily operations
│       ├── products_tab.py              # Product management
│       ├── clients_tab.py               # Client management
│       ├── suppliers_tab.py             # Supplier management
│       └── log_tab.py                   # Activity log
├── core/
│   ├── __init__.py
│   ├── password.py                      # Password management and validation
|   ├── profiles.py                      # Profiles management and validation
│   └── database.py                      # SQLite interface with encryption
├── managers/
│   ├── __init__.py
│   ├── products_manager.py              # Product business logic
│   ├── clients_manager.py               # Client business logic
│   ├── suppliers_manager.py             # Supplier business logic
│   ├── sales_manager.py                 # Sales operations
│   ├── inventory_manager.py             # Inventory tracking
│   └── receipts_manager.py              # Receipt management
├── events/
│   ├── __init__.py
│   ├── products_events.py               # Product-related events
│   ├── clients_events.py                # Client-related events
│   ├── suppliers_events.py              # Supplier-related events
│   └── sales_events.py                  # Sales-related events
└── profiles/                            # User profiles storage
    ├── profile1/
    │   ├── inventory.db                 # SQLite database
    │   └── profile_config.json          # Profile settings
    └── profile2/
        ├── inventory.db
        └── profile_config.json
```

## Core Components

### Password System (`core/password.py`)
- **State Management:** `isCorrect` boolean property
- **Validation:** `validator(password)` method returns True/False
- **Session Management:** `logout()` method resets authentication state
- **Encryption Key:** Derives encryption key from password for database operations

### Database Interface (`core/database.py`)
- **Abstraction Layer:** Simplifies SQLite operations
- **Encryption Handling:** Transparent encrypt/decrypt operations
- **Profile Isolation:** Manages separate database files per profile
- **Data Integrity:** Ensures consistent database operations

### Widget Architecture (`ui/widgets/`)
- **Themed Widgets:** Consistent dark mode styling across application
- **Reusable Components:** Prevents widget recreation, promotes consistency
- **Custom Widgets:** Specialized grouped widgets for complex UI elements

## Design Principles

1. **Simplicity:** No external dependencies, no server setup, no internet required
2. **Portability:** Complete profile folders can be moved between devices
3. **Security:** Optional encryption with password protection
4. **Maintainability:** Clear separation of concerns between UI, business logic, and data
5. **User Experience:** Dark mode throughout, intuitive navigation, visual feedback
6. **Performance:** SQLite for efficient data operations, minimal memory usage