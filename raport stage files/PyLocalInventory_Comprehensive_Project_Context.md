# PyLocalInventory — Comprehensive Project Context Document
## Knowledge Base for Internship Report / Another AI Model

**Purpose:** This document consolidates the factual project knowledge available from prior PyLocalInventory discussions, handoff documents, logs, code excerpts, and project-related conversations. It is a **knowledge base**, not the final internship report.

**Evidence rule:**  
- **[CONFIRMED]** = explicitly established in prior discussions/files.  
- **[LIKELY]** = strongly supported by the available project material but not explicitly established as a final fact.  
- **[UNCERTAIN]** = conflicting or incomplete information exists.  
- **[UNKNOWN]** = not available from the preserved context.

> Important: This document deliberately distinguishes historical code, requested features, reported fixes, and final/active state. A feature mentioned as a requirement is not automatically treated as implemented.

---

# 1. Internship Information

## 1.1 Company / organization

- **[CONFIRMED] Company:** **LAMIDAP**.
- **[CONFIRMED]** The PyLocalInventory work was associated with LAMIDAP and its business operations.
- Historical report branding explicitly contained:
  - LAMIDAP SARL
  - 288, Zone Industrielle Gzenaya
  - 90000 Tanger
  - +212 539 39 45 60
  - lamidap@gmail.com
  - ICE / IF / RC / Patente / CNSS
  - bank / RIB information.
- **[CONFIRMED] Professional internship supervisor:** **Marouan Laghmich**.
- **[UNKNOWN] Internship department/service:** no reliable exact department name is preserved.
- **[UNKNOWN] Exact internship start/end dates:** the available context only establishes that the internship was updated from one month to **two months**. Exact dates are not preserved here.

## 1.2 Internship duration

- **[CONFIRMED] Duration was changed/clarified to two months** in previous internship discussions.
- **[UNKNOWN] Exact calendar dates.**

## 1.3 Internship objectives

The exact official internship objectives were not preserved as a formal company document. The project work shows these practical objectives:

- [CONFIRMED/LIKELY] Develop or improve a desktop business-management application for inventory and commercial operations.
- [CONFIRMED] Manage products, services, clients, suppliers, sales, imports, payments and reports.
- [CONFIRMED] Provide LAN Host/Client operation with a central PostgreSQL database.
- [CONFIRMED] Improve application reliability and GUI responsiveness.
- [CONFIRMED] Produce printable business documents/PDF reports.
- [CONFIRMED] Support real business workflows rather than only a demonstration/prototype.
- [CONFIRMED] Support permissions and multiple users.
- [LIKELY] Reduce manual work and centralize operational/business information.

## 1.4 Project name/title

- **[CONFIRMED] Project:** **PyLocalInventory**.
- **[CONFIRMED] Type:** Windows desktop inventory / sales / imports / payments / reports application.

A suitable report title can be formulated later, but the exact official French title is **[UNKNOWN]**.

## 1.5 Project context

PyLocalInventory is a desktop application designed around the operational needs of a business handling products/materials, customers, suppliers, sales, imports, payments and commercial documents.

The application evolved from an earlier architecture and underwent substantial stabilization and modernization work. The final intended architecture uses:

- Python
- PySide6 / Qt
- PostgreSQL
- Host/Client LAN architecture
- an existing RPC/API network layer
- PyInstaller for packaging
- PowerShell build tooling.

The project was not simply a CRUD exercise. A large portion of the work concerned making real desktop workflows safe under asynchronous execution, LAN communication, database access and repeated user interaction.

## 1.6 Problem the project addresses

The application exists to centralize business operations that otherwise require fragmented/manual management:

- product and stock management;
- customer and supplier information;
- sales;
- imports/stock entries;
- payments and client balances;
- quotations/devis;
- delivery notes;
- invoices and receipts;
- reports/PDF generation;
- attachments;
- backups;
- user/role permissions;
- operational and financial dashboards.

The available context does **not** preserve the company's original manual process in enough detail to state exactly which paper/software process was replaced. Therefore, avoid claiming a specific previous system unless the company confirms it.

## 1.7 Why the project was needed

[CONFIRMED/LIKELY] The system was needed to provide a unified, persistent and multi-user business-management environment, while preserving reliable stock and financial calculations.

The Host/Client architecture is particularly important because several computers can access the same authoritative business database through the LAN.

---

# 2. Project Overview

## 2.1 Main idea

PyLocalInventory is a Windows desktop business-management application centered on inventory and commercial operations.

Its main business objects are:

- Products
- Services
- Clients
- Suppliers
- Sales
- Sale Items
- Imports
- Import Items
- Payments
- Reports
- Attachments
- Historical Sales
- Client balances
- Users / roles / permissions
- Profiles / connection configuration.

Additional later functionality includes Charges and Analytics / Net Profit.

## 2.2 Purpose

The purpose is to allow business users to:

1. maintain a product/service catalog;
2. maintain clients and suppliers;
3. record purchases/imports and update stock;
4. record sales and update stock;
5. track payments and outstanding balances;
6. generate quotations and commercial PDFs;
7. attach documents;
8. inspect client financial history;
9. monitor stock and financial indicators;
10. work from multiple LAN-connected computers;
11. control access through users, roles and permissions;
12. back up the database.

## 2.3 Target users

- [CONFIRMED] Business users/operators using the desktop application.
- [CONFIRMED] Host/local users connected directly to PostgreSQL.
- [CONFIRMED] Remote Client users connected through the LAN RPC layer.
- [CONFIRMED] Users with permissions defined by roles.
- [UNKNOWN] Exact job titles of all real employees.

## 2.4 User roles

The application has a user/role/permission system.

- [CONFIRMED] Network access uses users, roles and role permissions.
- [CONFIRMED] Permissions can control read/write/delete operations by section.
- [CONFIRMED] Sections include Products, Sales, Imports, Clients, Suppliers and Reports.
- [UNKNOWN] The exact final list of role names and every permission value is not preserved.
- [CONFIRMED] Example usernames visible in logs included `saad`, `haitam`, `DefaultUser`, and profile/branch names such as `hazim`; these are not proof of formal job roles.

## 2.5 Main use cases

### Product management
- Create, view, edit and manage products.
- Track stock.
- Configure low-stock alert behavior.
- Use products inside sales/imports.

### Service management
- Manage services separately from physical products.

### Client management
- Create/view/edit clients.
- View client account.
- Review purchases/sales history.
- Review payment history.
- Calculate total bought, total paid and remaining balance.
- Edit a selected payment amount.
- Print selected sale.
- Print complete client statement.
- Manage client attachments.

### Supplier management
- Manage suppliers.
- Use suppliers in imports.
- View supplier information.

### Sales management
- Create new sale.
- Edit existing sale.
- Add products/services and quantities.
- Set unit prices.
- Apply discount (`Remise`).
- Calculate HT, TVA and TTC.
- Associate sale with a client.
- Add notes.
- Save sale and sale items.
- Update stock for normal sales.
- Support historical sales that do not affect current stock.
- Generate/display persistent Devis reference.
- Generate commercial reports/PDF.

### Import management
- Create/edit imports.
- Add import items.
- Associate supplier.
- Update stock.
- Support historical import behavior where applicable.
- Generate Bon de Livraison functionality was requested.
- Attach documents.

### Payment management
- Record payments.
- Associate payments with sales.
- Display payment history.
- Edit selected payment amount.
- Update client totals.
- Prevent payment duplication.
- Do not affect stock when editing a payment.

### Reports
- Generate Devis.
- Generate invoices.
- Generate delivery notes.
- Generate payment receipts.
- Generate client statements.
- Preview/print PDFs.
- Store/report generated document information.

### Dashboard / analytics
- Show key statistics.
- Show low-stock alerts.
- Show monthly financial overview.
- Show sales/imports/profit indicators.
- Quick actions.
- Later Analytics functionality includes Net Profit.

### Charges
A later feature set added a Charges module with:
- charge categories;
- recurring charge templates;
- charges;
- CRUD;
- recurring charges;
- attachments;
- filters;
- permissions;
- RPC access;
- Analytics Net Profit integration.

The exact UI fields of the final Charges implementation are not fully preserved.

---

# 3. Requirements

## 3.1 Functional Requirements

### FR-01 — Product management
The system shall manage products and their operational data, including stock and pricing information.

### FR-02 — Service management
The system shall maintain services independently from products.

### FR-03 — Client management
The system shall allow authorized users to create, read and update client records and inspect their account history.

### FR-04 — Supplier management
The system shall allow authorized users to manage supplier records.

### FR-05 — Sales
The system shall allow authorized users to create and edit sales containing multiple line items.

### FR-06 — Sale calculations
The application shall calculate:
`Original Subtotal = sum(quantity × unit price)`
`Total HT = Original Subtotal - Remise`
`TVA = Total HT × VAT rate`
`Total TTC = Total HT + TVA`

### FR-07 — Sale stock management
Normal sales decrease stock correctly.

### FR-08 — Historical sales
A historical sale must not modify current stock.

### FR-09 — Sale editing
Editing an existing sale must:
- avoid duplicate sale creation;
- avoid double stock deduction;
- update totals correctly.

### FR-10 — Devis references
The sale/devis reference system is designed around:
`DE-YEAR-NUMBER`

Examples:
- `DE-2026-1`
- `DE-2026-525`

Requirements:
- auto-generated;
- auto-incremented;
- persistent;
- editable;
- unique;
- safe across restart;
- safe in client mode;
- concurrency-safe;
- displayed in Sales, Add/Edit Sale, View Client, reports and Client Statement.

### FR-11 — Imports
The system shall manage imports and import items and update stock.

### FR-12 — Payments
The system shall record payments and associate them with sales and client accounts.

### FR-13 — Payment editing
Editing a selected payment must:
- affect only the selected payment;
- validate amount safely;
- update account totals;
- not affect stock;
- not create duplicate payments.

### FR-14 — Client account
The client account displays:
- client information;
- Total Bought;
- Total Paid;
- Remaining;
- Sales History;
- Payment History;
- Print Selected Sale;
- Print Full Client Statement;
- Edit Payment Amount;
- scrolling.

Requested Sales History columns:
- Sale #
- Date
- Devis

Requested Payment History columns:
- Payment #
- Sale #
- Date
- Amount
- Devis

One Sale must appear once, not once per Sale Item.

### FR-15 — Attachments
The system supports uploading/listing/thumbnail access for attachments associated with business entities such as sales and clients.

### FR-16 — Reports/PDF
The system generates printable documents using HTML/CSS templates and PDF engines.

### FR-17 — Bon de Livraison
A Bon de Livraison workflow was requested for Imports:
- select an Import;
- generate professional PDF;
- supplier information;
- import date;
- import items/quantities;
- multi-page support;
- persistent BL reference if implemented.

Preferred format:
`BL-2026-1`, `BL-2026-2`.

The exact final implementation state of persistent BL numbering is **[UNCERTAIN]**.

### FR-18 — Dashboard
The Home dashboard includes:
- visual analytics;
- low-stock alert;
- monthly financial overview;
- sales;
- imports/import costs;
- profit;
- quick actions such as New Sale and New Import.

### FR-19 — Charges
The later Charges feature set includes:
- named categories/templates;
- CRUD;
- recurring charges;
- attachments;
- filters;
- permissions;
- RPC access;
- Analytics Net Profit.

### FR-20 — Users/roles/permissions
The server enforces permissions for network users and sections.

### FR-21 — Profiles
Profiles hold connection/company configuration and are protected through profile password logic.

### FR-22 — Backups
Database backup functionality exists as a major module and `core/pg_backup.py` is part of the architecture.

---

## 3.2 Non-Functional Requirements

### Security
- [CONFIRMED] Profile password protection uses Fernet through `cryptography`.
- [CONFIRMED] Network users have roles and permissions.
- [CONFIRMED] Server-side permission checks are performed before protected database operations.
- [CONFIRMED] Passwords/profile-sensitive data should not be pushed to Git.
- [CONFIRMED] The architecture avoids creating a second source of truth.

### Performance
- [CONFIRMED] Avoid synchronous database/RPC operations on the GUI thread.
- [CONFIRMED] Avoid per-row product/detail calls (N+1 behavior).
- [CONFIRMED] Use asynchronous loading/saving where appropriate.
- [CONFIRMED] Prefetch catalog data instead of repeated LAN lookups in Sale Save.
- [CONFIRMED] Use session cache and disk cache mechanisms in some tab flows.
- [CONFIRMED] Dashboard refresh was configured for every 30 seconds.
- [CONFIRMED] Attachment thumbnails were identified as a potential expensive operation.

### Usability
- Responsive GUI.
- Clear tab-based organization.
- Quick actions.
- Client account summaries.
- Tables with search/sort/refresh behavior.
- Printable business documents.
- Multi-language UI strings exist in English/French/Spanish in at least some modules.

### Reliability
- Prevent duplicate saves.
- Prevent duplicate sales.
- Prevent double stock deductions.
- Preserve transaction integrity.
- Handle thread lifecycle safely.
- Handle application shutdown safely.
- Prevent native Qt crashes.
- Maintain PostgreSQL as authoritative source.

### Maintainability
- Separate `classes/`, `core/`, `ui/`, `server/`, `report/`, `tests/`.
- Reusable `BaseOperationDialog`.
- Reusable `OperationsTableWidget`.
- Centralized business logic in model/core layers.
- Automated tests.
- Logging and diagnostics.

### Scalability
- LAN Host/Client architecture.
- PostgreSQL as central authoritative database.
- Connection pooling with `ThreadedConnectionPool`.
- Avoid N+1 requests.
- Asynchronous UI operations.

### Compatibility / deployment
- Windows desktop.
- Packaged with PyInstaller.
- Build process automated through `build_windows.ps1`.

---

# 3.3 Business Rules

1. [CONFIRMED] Host PostgreSQL is the authoritative database.
2. [CONFIRMED] `ENABLE_SQLITE_CACHE = False`.
3. [CONFIRMED] `ENABLE_INCREMENTAL_SYNC = False`.
4. [CONFIRMED] Do not introduce SQLite replication/synchronization as a second source of truth.
5. [CONFIRMED] Normal Sale decreases stock.
6. [CONFIRMED] Historical Sale does not affect current stock.
7. [CONFIRMED] Editing an existing Sale must not double-decrease stock.
8. [CONFIRMED] One save action should correspond to one transaction.
9. [CONFIRMED] No duplicate Sale should be created by duplicate Save clicks.
10. [CONFIRMED] Devis references must remain persistent and unique.
11. [CONFIRMED] Payment editing must not affect stock.
12. [CONFIRMED] Sales History must not duplicate a Sale once per line item.
13. [CONFIRMED] Permissions are enforced server-side.
14. [CONFIRMED] GUI widgets must not be accessed from worker threads.
15. [CONFIRMED] Worker callbacks that touch Qt widgets must execute on MainThread.
16. [CONFIRMED] QThread references should not be cleared before thread completion.
17. [CONFIRMED] No `terminate()` for normal worker cancellation.
18. [CONFIRMED] Cooperative interruption uses `requestInterruption()` and `quit()`.
19. [CONFIRMED] Database connections must not be shared unsafely across threads.
20. [CONFIRMED] Report worker `_PdfRenderWorker` uses a dedicated Database connection in local/host mode.

---

# 4. Technologies and Tools

## 4.1 Python
**[CONFIRMED]** Main programming language.

Used for:
- application logic;
- model/business classes;
- database access;
- networking;
- GUI;
- reports;
- diagnostics;
- testing;
- build/support scripts.

Why:
- native fit for desktop automation/business tooling;
- strong Qt bindings;
- PostgreSQL ecosystem;
- rapid development.

## 4.2 PySide6 / Qt
**[CONFIRMED]** GUI framework.

Modules explicitly observed:
- `PySide6.QtWidgets`
- `PySide6.QtCore`
- `PySide6.QtGui`
- `PySide6.QtPrintSupport`

Used for:
- main window;
- tabs;
- dialogs;
- tables;
- forms;
- buttons;
- charts/dashboard;
- asynchronous worker/thread integration;
- print/preview UI.

## 4.3 PostgreSQL
**[CONFIRMED]** Current authoritative database engine.

Used for:
- Products;
- Services;
- Clients;
- Suppliers;
- Sales;
- Sale Items;
- Imports;
- Import Items;
- Reports;
- Payments;
- Users/roles/permissions;
- later charge-related data.

Why:
- central authoritative relational database;
- supports multi-user LAN architecture;
- transactional integrity;
- server-side access control;
- connection pooling.

## 4.4 psycopg2 / psycopg2-binary
Used to connect Python to PostgreSQL.

Files:
- `core/database.py`
- `core/pg_config.py`
- `core/pg_backup.py`
- `core/network/server.py`

`psycopg2.pool.ThreadedConnectionPool` is used on the server.

## 4.5 cryptography / Fernet
Used in `core/password.py` for profile password protection and encrypted validation phrase handling.

## 4.6 HTML / CSS
Used for report templates:
- Devis;
- invoices;
- delivery notes;
- payment receipts;
- printable reports.

## 4.7 PDF generation
Dependencies:
- `playwright`
- `xhtml2pdf`
- `weasyprint`
- `pdfkit`

Reported fallback order:
1. Playwright
2. xhtml2pdf
3. WeasyPrint
4. PDFKit
5. HTML fallback.

Playwright Chromium was actually observed in report logs.

## 4.8 PyInstaller
Used to package the Windows application into an executable.

Relevant:
- `PyLocalInventory.spec`
- `build_windows.ps1`

## 4.9 PowerShell
Used for Windows build commands, e.g.:
`powershell -ExecutionPolicy Bypass -File .\build_windows.ps1`

## 4.10 Python standard library
Explicitly observed/mentioned:
- os
- sys
- json
- shutil
- subprocess
- tempfile
- socket
- threading
- datetime
- glob
- html
- base64
- hashlib
- secrets
- http.server

## 4.11 Development tools
- Windows
- VS Code
- OpenCode
- PowerShell
- Git
- Python virtual environment (`.venv`).

## 4.12 Version control
Git was used with branches including:
- `haitam`
- `lamibois`
- `hazim`

Branch strategy was used for company-specific branding.

## 4.13 No web frontend framework
The preserved project context identifies PyLocalInventory as a Windows desktop PySide6 application. Do not describe it as a Laravel/Vue/web application; that belongs to other projects.

---

# 5. System Architecture

## 5.1 Overall architecture

The intended architecture is:

**Windows Desktop Client**
→ **PySide6 GUI**
→ **application/core/business layer**
→ either:
- direct/local PostgreSQL access in Host/local mode, or
- LAN RPC/API client → Host RPC/API server → PostgreSQL.

The Host PostgreSQL database is the single authoritative source.

## 5.2 Host/Client architecture

### Host
- Runs PostgreSQL.
- Runs the application/server-side network component.
- Acts as authoritative data source.
- Exposes controlled operations through the existing RPC/API layer.

### Client
- Runs the PySide6 application.
- Uses `core/network/client.py`.
- Sends RPC calls to Host.
- Receives data and renders it locally.

### Server
`core/network/server.py`
- HTTP/JSON-based local network server.
- Uses PostgreSQL connection pooling.
- Checks user permissions.
- Executes allowed operations.

### Client networking
`core/network/client.py`
- Sends RPC calls.
- Receives results.
- Logs host/port/duration/build IDs.

## 5.3 API/RPC architecture

Examples observed:
- `get_items`
- `cursor.execute`
- `save_sale_with_items`
- `get_items_by_operation_id`
- `get_client_sales`
- `list_attachments`
- `upload_attachment`
- `get_attachment_thumbnail`

The server checks permissions for methods such as database cursor execution.

Example log pattern:
`LAN RPC method=save_sale_with_items`

## 5.4 Authentication flow

Two security mechanisms exist.

### Profile-level protection
`core/password.py`
- Uses Fernet encryption.
- Validates an encrypted phrase.
- Protects profile access.

### Network users
`core/user_manager.py`
`core/network/server.py`
`core/network/protocol.py`

The network server associates operations with users and checks permissions.

## 5.5 Authorization

Permission enforcement is server-side.

A logged example explicitly showed:
- user ID;
- requested method;
- table/section;
- normalized section;
- required permission;
- remote mode.

Example:
`table='Clients' normalized_section=Clients needed=read mode=remote`

## 5.6 Data flow: Sale creation

1. User opens Sales.
2. Sales tab opens `SalesEditDialog`.
3. Dialog uses `BaseOperationDialog`.
4. Items are entered in `OperationsTableWidget`.
5. Each row becomes a `SalesItemClass`.
6. Sale becomes a `SalesClass`.
7. Database layer writes the sale to `Sales`.
8. Line items are written to `Sales_Items`.
9. Totals, VAT, payment state and reporting information derive from persisted data.

For client mode, network calls pass through the RPC layer.

## 5.7 Important architectural decision

The project deliberately rejected adding SQLite replication/synchronization as an authoritative mechanism.

Current required flags:
- `ENABLE_SQLITE_CACHE = False`
- `ENABLE_INCREMENTAL_SYNC = False`

The reason is to avoid:
- two sources of truth;
- synchronization conflicts;
- architectural complexity;
- inconsistent stock/business state.

## 5.8 Threading architecture

The GUI uses QThread-based workers for operations that could block.

Rules established:
- strong worker reference;
- strong thread reference;
- move worker correctly;
- worker does not touch QWidget;
- callbacks to GUI on MainThread;
- no `terminate()`;
- cooperative cancellation;
- `requestInterruption()`;
- `quit()`;
- bounded `wait()` only where appropriate;
- no ordinary GUI blocking with `wait()`;
- clear references only after `thread.finished`;
- identity-safe cleanup;
- duplicate workers prevented;
- stale results ignored.

---

# 6. Database

## 6.1 Database type

- **[CONFIRMED FINAL ARCHITECTURE] PostgreSQL**
- **[CONFIRMED HISTORICAL ARTIFACT]** older project code contained SQLite-related infrastructure and migrations.
- Therefore, the report should describe PostgreSQL as the final authoritative architecture and mention historical SQLite/cache code only if discussing project evolution.

## 6.2 Known logical tables / data areas

The preserved project context identifies:

- `Products`
- `Services`
- `Clients`
- `Suppliers`
- `Sales`
- `Sales_Items`
- `Imports`
- `Import_Items`
- `Payments`
- `Reports`
- `Attachments`
- `Historical Sales` / historical-sale data
- client balance-related data
- Users / roles / permissions
- later:
  - `charge_categories`
  - `charge_recurring_templates`
  - `charges`

**Important:** Exact final PostgreSQL schema names for every later table are not fully preserved. Do not invent columns.

## 6.3 Known columns / fields

### Clients
Explicitly observed:
- `ID`
- `username`
- `address`
- `phone`
- `email`
- `ice`

Example query:
`SELECT address, phone, email, ice FROM Clients WHERE ID = %s`

### Products
Explicitly observed:
- `ID`
- `name`
- `unit_price`

Example query:
`SELECT ID, name, unit_price FROM Products WHERE name = %s`

Other product fields clearly existed because stock and alert levels are used, but exact final column names are **[UNKNOWN]**.

### Sales
Explicitly observed logically:
- `id` / `ID`
- client relationship (`client_id`)
- `client_username` was observed in a query
- Devis reference
- state
- notes
- date
- total HT
- total TTC
- discount/remise
- VAT
- payment state/related information.

Exact final PostgreSQL column list and data types are **[UNCERTAIN]**.

### Sales_Items
Explicitly known logically:
- item ID
- `sales_id`
- product relation / product identifier
- quantity
- unit price
- line total/product name information.

Exact final PostgreSQL column names are **[UNCERTAIN]**.

### Imports
Explicitly known:
- ID
- supplier relationship
- date
- import items
- quantities
- stock impact.

Exact final PostgreSQL column list is **[UNKNOWN]**.

### Import_Items
Explicitly known:
- item ID
- `import_id`
- product information
- quantity
- price/cost information.

Exact final PostgreSQL schema is **[UNCERTAIN]**.

### Payments
Known logically:
- payment ID
- sale ID
- date
- amount
- Devis relationship/reference.

Exact final column names are **[UNCERTAIN]**.

### Attachments
Known:
- attachment entity type;
- entity ID;
- upload/list/thumbnail operations.

Example RPC:
`upload_attachment ... entity_type=sale entity_id=22`
`list_attachments ... entity_type=sale entity_id=22`
`get_attachment_thumbnail ... entity_type=...`

Exact attachment table schema is **[UNKNOWN]**.

## 6.4 Known relationships

- Client → Sales: one client can have many sales.
- Sale → Sale Items: one Sale has many Sale Items.
- Import → Import Items: one Import has many Import Items.
- Sale → Payments: one Sale can have multiple payments.
- Client → Payments indirectly through Sales.
- Supplier → Imports: one supplier can have multiple imports.
- Product → Sale Items: a product can appear in many sale items.
- Product → Import Items: a product can appear in many import items.
- Attachments can belong to multiple entity types.

## 6.5 Foreign keys

Historical code explicitly used:
- `sales_id` → `Sales(ID)` with `ON DELETE CASCADE`
- `import_id` → `Imports(ID)` with `ON DELETE CASCADE`

Historical SQLite migration code also discussed relaxing a `product_id` foreign key in `Sales_Items` and `Import_Items`; this belongs to the historical architecture and should not automatically be presented as the final PostgreSQL constraint.

## 6.6 Database design decisions

- PostgreSQL is authoritative.
- Transactions are important for Sale/Import operations.
- One action should produce one transaction.
- Avoid duplicate Sale.
- Avoid double stock deduction.
- Avoid N+1 database/RPC calls.
- Use connection pooling server-side.
- Use dedicated worker DB connections where thread ownership requires it.

## 6.7 Database migrations / historical architecture

The older SQLite-oriented code contained:
- `Meta` table;
- migration flags;
- `fk_relaxed`;
- `backfill_product_name_done`;
- `BEGIN EXCLUSIVE`;
- WAL mode;
- `busy_timeout=5000`.

This proves historical SQLite migration logic existed, but **does not prove it remains active in the final PostgreSQL architecture**.

## 6.8 MCD / MLD / ERD / UML

- **[UNKNOWN]** No final MCD/MLD/ERD/UML diagram is preserved in the accessible project context.
- The logical relationships above can be used later to construct a verified diagram, but an AI writing the report must not claim that a formal diagram was produced unless the actual diagram is supplied.

---

# 7. User Interface / UX

## 7.1 Main modules/tabs

Known modules:
- Home
- Products
- Services
- Clients
- Suppliers
- Sales
- Imports
- Reports
- Payments
- Attachments
- Backups
- Users / Roles / Permissions
- Profiles / connection configuration
- Charges
- Analytics.

## 7.2 Home / Dashboard

Known elements:
- Visual Analytics;
- Low Stock Alert;
- Monthly Financial Overview;
- Sales;
- Imports;
- Imports (Cost);
- Profit;
- Quick Actions;
- New Sale;
- New Import.

The dashboard refresh timer was set to 30 seconds.

## 7.3 Products

Purpose:
- manage product catalog and stock.

Known UX:
- table/list;
- search/sort/refresh;
- product selection in sales/imports;
- low-stock monitoring.

Exact final buttons/forms are **[UNCERTAIN]**.

## 7.4 Services

Purpose:
- manage non-product services.

Exact final UI is **[UNKNOWN]**.

## 7.5 Clients

Purpose:
- manage customers and open detailed account view.

Important behavior:
- first activation should issue one request;
- duplicate activation suppressed;
- stale responses ignored;
- newest valid response accepted;
- failed request resets state;
- manual Refresh should issue one request;
- closed tab must not receive results.

## 7.6 View Client / Client Account

File:
`ui/dialogs/client_details_dialog.py`

Elements:
- client information;
- Total Bought;
- Total Paid;
- Remaining;
- Sales History;
- Payment History;
- Print Selected Sale;
- Print Full Client Statement;
- Edit Payment Amount;
- scrolling.

Sales History:
- Sale #
- Date
- Devis

Payment History:
- Payment #
- Sale #
- Date
- Amount
- Devis

Important UX requirement:
- Sales and Payment History should appear side-by-side horizontally where practical.

## 7.7 Suppliers

Purpose:
- manage supplier records;
- use suppliers in Imports.

A "View Supplier" capability was requested as an analogue to "View Client".

Exact final layout is **[UNCERTAIN]**.

## 7.8 Sales

Sales management table requested columns:
- ID
- Devis
- State
- Client Name
- Notes
- Date
- Total HT
- Total TTC

Actions:
- Add Sale
- Edit Sale
- view details
- save
- print/report.

## 7.9 Add/Edit Sale

Primary architecture:
`ui/dialogs/edit_dialogs/base_operation_dialog.py`

Sale-specific class:
`SaleEditDialog`

Item table:
`ui/widgets/operations_table.py`

Observed source:
`ui/dialogs/edit_dialogs/sale_dialog.py`

`SaleEditDialog` creates/loads:
- `SalesClass`
- `SalesItemClass`

New sale default date is set to today.

## 7.10 Imports

Actions:
- Add Import
- Edit Import
- Save Import
- stock update
- attachments
- requested Bon de Livraison.

## 7.11 Reports

Relevant:
`ui/dialogs/reports_dialog.py`

Documents:
- Devis
- Invoice
- Delivery Note
- Payment Receipt
- Client Statement
- printable report layouts.

## 7.12 Charges

Later feature:
- categories;
- recurring templates;
- charges;
- filters;
- attachments;
- permissions;
- analytics.

Exact final UI design is **[UNKNOWN]**.

## 7.13 Analytics

Later feature:
- Net Profit analytics;
- integration with charges;
- dashboard/financial visualization.

Exact final chart types are **[UNCERTAIN]**.

---

# 8. Features Implemented

## 8.1 Core inventory
**What:** Product/service/client/supplier management.  
**Why:** Centralize master data.  
**Users:** Authorized users.  
**Technical:** Model classes + PostgreSQL + PySide6 tables/dialogs.  
**Status:** [CONFIRMED as core application functionality].

## 8.2 Sales
**What:** Multi-item sales.  
**Why:** Record commercial transactions.  
**Technical path:** Sales tab → `SalesEditDialog` → `BaseOperationDialog` → `OperationsTableWidget` → `SalesClass`/`SalesItemClass` → DB/RPC.  
**Status:** [CONFIRMED core functionality], but Sale Save had serious historical stability problems and must be described carefully in the testing/status section.

## 8.3 Sale calculations
Formulas:
- Original Subtotal = sum(quantity × unit price)
- Total HT = Original Subtotal - Remise
- TVA = Total HT × VAT rate
- Total TTC = Total HT + TVA

**Status:** [CONFIRMED].

## 8.4 Historical Sale
**Purpose:** record historical business data without modifying current stock.  
**Status:** [CONFIRMED as required business behavior]; exact final manual UI flow is [UNCERTAIN].

## 8.5 Devis
**Reference:** `DE-YEAR-NUMBER`.  
**Status:** [CONFIRMED as implemented/required persistent Sale reference system in the handoff].  
A real generated PDF with `DE-2026-1` was observed.

## 8.6 Client Account
Features:
- totals;
- remaining balance;
- sales history;
- payment history;
- printing;
- payment editing.

**Status:** [CONFIRMED].

## 8.7 Payments
**Status:** [CONFIRMED core feature], including editing selected payment and linking payment to sale/devis.

## 8.8 Reports/PDF
**Status:** [CONFIRMED].

A real report log showed:
- PDF engine: Playwright Chromium;
- successful Devis generation;
- generated path;
- client mode.

Example observed generated document:
`DEVIS_DOC-000002_2026-08-05_112109.pdf`

## 8.9 Attachments
**Status:** [CONFIRMED].

Observed RPC methods:
- `upload_attachment`
- `list_attachments`
- `get_attachment_thumbnail`

## 8.10 Dashboard
**Status:** [CONFIRMED].

## 8.11 Host/Client LAN
**Status:** [CONFIRMED].

## 8.12 Users/roles/permissions
**Status:** [CONFIRMED].

## 8.13 Backups
**Status:** [CONFIRMED as a project module], exact UI/backup workflow [UNCERTAIN].

## 8.14 Charges
**Status:** [CONFIRMED as a later implemented feature set according to project handoff/history]:
- charge categories;
- recurring templates;
- charges;
- CRUD;
- recurring charges;
- attachments;
- filters;
- permissions;
- RPC access;
- Analytics Net Profit.

## 8.15 Analytics / Net Profit
**Status:** [CONFIRMED as later implemented functionality according to the project history], but exact final formulas and chart presentation are [UNCERTAIN].

## 8.16 Bon de Livraison
**Status:** [UNCERTAIN].
The feature was explicitly requested and integrated into the Imports workflow concept. The handoff warns that persistent BL reference was conditional ("if implemented"), so the report should not state that persistent BL numbering was completed without current-project verification.

---

# 9. Technical Implementation

## 9.1 Project structure

Important folders/files:

```text
main.py
auth/
classes/
core/
database/
ui/
server/
report/
scripts/
tests/
tools/
profiles/
README.md
requirements.txt
PyLocalInventory.spec
build_windows.ps1
assets/
LICENSE
.gitignore
.gitattributes
```

## 9.2 Business classes

Explicitly observed:
- `SalesClass`
- `SalesItemClass`
- `ProfileClass`

Other classes clearly exist but exact names are not fully preserved.

## 9.3 Core files

Important files:
- `core/database.py`
- `core/calculations.py`
- `core/password.py`
- `core/user_manager.py`
- `core/pg_config.py`
- `core/pg_backup.py`
- `core/memory_utils.py`
- `core/diagnostics.py`
- `core/network/server.py`
- `core/network/client.py`
- `core/network/protocol.py`
- `core/sync.py`
- `core/session_cache.py`

## 9.4 UI files

Explicitly observed:
- `ui/main_window.py`
- `ui/dialogs/reports_dialog.py`
- `ui/dialogs/client_details_dialog.py`
- `ui/dialogs/edit_dialogs/base_operation_dialog.py`
- `ui/dialogs/edit_dialogs/sale_dialog.py`
- `ui/widgets/operations_table.py`
- `ui/tabs/home_tab.py`
- `ui/tabs/base_tab.py`

## 9.5 Sale Save

Important implementation principle:
- GUI collects/validates data.
- Plain data payload is passed to worker.
- Worker does not access Qt widgets.
- Database/RPC work occurs outside GUI thread.
- Success/failure callback returns to MainThread.
- Thread references are retained until `thread.finished`.

The goal is:
- no GUI freeze;
- no duplicate Sale;
- no double stock deduction;
- no native crash.

## 9.6 OperationsTableWidget

File:
`ui/widgets/operations_table.py`

Historical bug:
An async refactor called nonexistent `load_data()`.

Correct method:
`refresh_table()`.

`refresh_table()` was updated to block table signals during programmatic reconstruction to avoid expensive `itemChanged` activity.

## 9.7 Decimal parsing

Historical errors:
- `decimal.InvalidOperation`
- `ConversionSyntax`

Fix:
safe parsing for:
- empty;
- None;
- localized input;
- partial/intermediate input;
- invalid final input;
- comma/dot formats;
- spaces/non-breaking spaces.

Save is blocked on invalid input.

## 9.8 Import SQL

Historical error:
`psycopg2.errors.UndefinedColumn: column si.information does not exist`

Cause:
Sales and Imports required different SQL projections.

Fix:
`get_operation_summary_items()` was corrected in `core/database.py`.

## 9.9 Reports threading

Historical report errors:
- `resource_path is not defined`
- worker missing `failed` signal
- `'qty'`
- raw `{{ placeholders }}`
- application closing during print
- thread-unsafe Qt print paths.

Architecture:
- report data gathering may run in background;
- Qt GUI printing/preview must remain on MainThread;
- `_PdfRenderWorker` later uses a dedicated Database connection for local/host mode rather than reusing GUI-thread psycopg2 connection.

## 9.10 Diagnostics

`core/memory_utils.py`:
- fixed Windows memory reporting.

`core/diagnostics.py`:
- adjusted watchdog logic to reduce false stall detection around Qt native `.exec()` waits.

Temporary diagnostic:
`logs/sale_save_hang_diagnostic.log`
- grew to approximately 100 MB;
- not intended for normal operation.

Normal logs:
- `logs/app.log`
- `logs/crash.log`

## 9.11 Logging rotation

A Windows issue occurred when stale Python processes held `app.log` open and prevented `RotatingFileHandler` rename/rollover.

A custom multi-process-safe rotating handler was planned/implemented in `core/diagnostics.py`.

## 9.12 Network connection examples

Observed LAN:
- port `8765`;
- host examples such as `192.168.100.33` and `192.168.0.133`;
- these are test/runtime environments, not necessarily permanent production configuration.

Build IDs were logged to detect Host/Client version mismatch.

---

# 10. Problems and Solutions

## Problem 1 — Sale Save freezes the application

**Problem:** Clicking Save on a Sale could produce:
`New Sale (Not Responding)` or `Python is not responding`.

**Cause:** Multiple interacting issues:
- synchronous GUI-thread DB/RPC lookups;
- repeated product/client/stock checks;
- unsafe worker callback threading;
- premature thread cleanup;
- worker/widget coupling.

**Investigation:** Real manual reproduction was required. Previous agents incorrectly claimed it was fixed based on isolated tests/code inspection.

**Solutions implemented/discussed:**
- prefetch catalog data;
- move blocking work off GUI thread;
- pass plain data to workers;
- use QObject-bound callbacks instead of unsafe lambdas;
- clean thread references only after `thread.finished`;
- prevent duplicate Save workers;
- maintain stock/business logic.

**Final result:** [UNCERTAIN historically]. A later focused stability pass passed automated tests, but a separate handoff still documented that real manual Sale Save could remain frozen. Therefore the report must not claim absolute resolution unless current runtime verification is available.

## Problem 2 — Lambda callback executes GUI code on worker thread

**Problem:** Pattern:
`worker.finished.connect(lambda result: self._on_save_finished(result, action))`

could execute callback in worker context.

**Cause:** Lambda was not safely bound to the GUI QObject context for the intended Qt connection behavior.

**Solution:** Use real QObject-bound methods/Slots.

**Result:** [CONFIRMED as a corrective architectural rule].

## Problem 3 — QThread destroyed while running

Errors:
- `QThread: Destroyed while thread is still running`
- `QThreadStorage`
- `Fatal Python error: Aborted`
- Windows access violation.

**Cause:** Thread/worker references were cleared too early.

**Solution:** Cleanup moved to handlers connected to `thread.finished`, e.g.:
- `_on_save_thread_finished`
- `_on_load_thread_finished`

**Result:** [CONFIRMED as a reported fix].

## Problem 4 — Deleted Qt wrapper

**Problem:** `thread.isRunning()` could be called after Qt deleted the native QThread.

**Cause:** Python/Shiboken wrapper outlived underlying Qt object.

**Solution:** identity-safe lifecycle management and avoid accessing deleted wrappers.

**Result:** [CONFIRMED fix direction].

## Problem 5 — Decimal.InvalidOperation

**Problem:** Numeric input could crash calculations.

**Cause:** Empty/None/localized/partial/invalid text was passed to Decimal parsing.

**Solution:** safe numeric parsing and validation.

**Result:** [CONFIRMED reported fixed].

## Problem 6 — Imports UndefinedColumn

**Problem:**
`column si.information does not exist`.

**Cause:** Import summary reused an incompatible SQL projection.

**Solution:** separate Sales and Imports SQL projections in `get_operation_summary_items()`.

**Result:** [CONFIRMED reported fixed].

## Problem 7 — Shutdown NameError

**Problem:**
`NameError: logger is not defined`.

**File:**
`ui/main_window.py`.

**Solution:** restore/properly define logger handling.

**Result:** [CONFIRMED reported fixed/tested].

## Problem 8 — OperationsTable async refactor called nonexistent method

**Problem:** `load_data()` did not exist.

**Solution:** use existing `refresh_table()`.

**Result:** [CONFIRMED].

## Problem 9 — Excessive itemChanged activity

**Problem:** Programmatic table reconstruction could trigger expensive item-change processing.

**Solution:** block table signals during reconstruction.

**Result:** [CONFIRMED].

## Problem 10 — Report resource path

**Problem:** `resource_path is not defined`.

**Solution:** report path/resource handling correction.

**Result:** [CONFIRMED as historical issue addressed].

## Problem 11 — Report worker missing `failed` signal

**Problem:** worker error path expected a signal that did not exist.

**Solution:** worker/report threading corrections.

**Result:** [CONFIRMED as historical issue addressed].

## Problem 12 — Report placeholder output

**Problem:** Raw `{{ placeholders }}` could appear in generated reports.

**Solution:** correct template rendering/data substitution.

**Result:** [CONFIRMED as historical issue addressed].

## Problem 13 — Application closes during print

**Cause:** thread-unsafe Qt print/preview path.

**Solution:** keep Qt GUI printing/preview on MainThread and isolate data gathering from GUI rendering.

**Result:** [CONFIRMED architecture].

## Problem 14 — Shared psycopg2 connection across threads

**Problem:** report worker could reuse a GUI-thread DB connection.

**Solution:** `_PdfRenderWorker` opens its own Database connection in local/host mode.

**Result:** [CONFIRMED].

## Problem 15 — N+1 queries/RPC calls

**Problem:** Sales could trigger repeated product lookups, sometimes once per row over LAN.

**Solution:** prefetch catalogs and use in-memory data.

**Result:** [CONFIRMED improvement].

## Problem 16 — False watchdog stalls

**Problem:** diagnostics could report stalls around Qt native `.exec()` waits.

**Solution:** watchdog logic adjustment.

**Result:** [CONFIRMED reported fix].

## Problem 17 — RAM always shown as 0.0 MB

**Solution:** `core/memory_utils.py` changed for proper Windows memory reporting.

**Result:** [CONFIRMED reported fix].

## Problem 18 — Mojibake / encoding in logs

**Problem:** diagnostic logs could show corrupted characters.

**Solution:** logging/diagnostic handling was adjusted.

**Result:** [CONFIRMED issue was investigated; exact final implementation detail is uncertain].

## Problem 19 — Log rotation blocked by stale process

**Problem:** Windows stale Python processes kept `app.log` open, preventing rotation.

**Solution:** custom multi-process-safe rotating handler was planned/implemented.

**Result:** [LIKELY/CONFIRMED depending on exact version; current context says planned/implemented].

## Problem 20 — Incremental sync failures

Logs showed test-generated errors such as:
`RuntimeError: boom:Clients`
and:
`RuntimeError: boom:Products`.

Also:
`RuntimeError: db locked`.

These came from test doubles in `tests/test_sync_coordinator.py`.

Important: the final architecture intentionally has:
`ENABLE_INCREMENTAL_SYNC = False`.

Therefore these logs should not be interpreted as proof that production synchronization is active.

## Problem 21 — Reports remote refresh API mismatch

Observed:
`'RemoteDatabase' object has no attribute 'get_items'`.

This indicates a historical client/report integration mismatch.

Exact final resolution is **[UNCERTAIN]**.

## Problem 22 — PostgreSQL 18 pg_hba.conf failure

**Latest preserved unresolved blocker in the handoff.**

Symptom:
`FATAL: could not load C:/Program Files/PostgreSQL/18/data/pg_hba.conf`

Settings observed:
- Host `192.168.100.11`
- Port `5432`
- Maintenance DB `postgres`
- User `postgres`
- PostgreSQL 18.

Evidence:
- `pg_isready` reported server accepting connections.
- direct `psql` also failed with same `pg_hba.conf` load error.
- file existed.
- PowerShell could read it.
- permissions showed access for Administrators, SYSTEM, local user and NetworkService.
- PostgreSQL service `postgresql-x64-18` was running as `NT AUTHORITY\NetworkService`.

A suspicious line:
`host all all 192.168.100.11 scram-sha-256`

might need CIDR (`/32` or `/24`), but this was **not to be changed blindly** because localhost also failed.

Required next investigation:
- PostgreSQL server logs;
- Windows Application Event Log;
- identify exact parse/load error.

Do NOT:
- reinstall PostgreSQL;
- run `initdb`;
- delete data directory;
- replace entire pg_hba.conf;
- reset database.

---

# 11. Development Process

## Phase 1 — Requirements analysis
[CONFIRMED/LIKELY]
- Identify inventory/business modules.
- Identify Products, Services, Clients, Suppliers, Sales, Imports, Payments and Reports.
- Later identify Charges and Analytics needs.
- Define multi-user Host/Client operation.

## Phase 2 — Specification
- Define business rules around stock, payments, sales and historical operations.
- Define persistent Devis reference.
- Define permissions.
- Define reporting requirements.
- Define company branding requirements.

## Phase 3 — System analysis
- Existing desktop architecture was analyzed.
- Host/Client RPC architecture preserved.
- PostgreSQL established as authoritative source.
- SQLite sync/replication explicitly disabled.

## Phase 4 — Database design
- Relational business entities.
- Sales and line items.
- Imports and line items.
- Payments.
- Client balances.
- Attachments.
- Users/permissions.
- Later charges.

Exact final ERD is unavailable.

## Phase 5 — UI/UX
- PySide6 tab-based desktop UI.
- Home dashboard.
- Management tables.
- Add/Edit operation dialogs.
- Client Account dialog.
- Reports/print dialogs.
- Quick actions.
- Low-stock and financial analytics.

## Phase 6 — Backend/core development
- Database layer.
- Business classes.
- Calculation logic.
- User management.
- Network server/client.
- Password protection.
- Backups.
- Diagnostics.
- Reporting.

## Phase 7 — Frontend/GUI development
- PySide6 widgets/dialogs/tabs.
- Operations table.
- asynchronous worker integration.
- dashboard refresh.
- client account.

## Phase 8 — Integration
- Local PostgreSQL.
- LAN RPC.
- Host/Client modes.
- PDF engine.
- attachments.
- permissions.

## Phase 9 — Testing
Testing became a major engineering phase because of native Qt/threading failures.

Focused testing included:
- calculations;
- QThread lifetime;
- remote workers;
- shutdown;
- operation summaries;
- recent changes;
- Sale Save;
- reports;
- Client Account.

## Phase 10 — Debugging
Repeated cycles:
1. reproduce;
2. inspect logs/stacks;
3. isolate root cause;
4. implement minimal fix;
5. run focused tests;
6. run broader suite;
7. manually verify real application.

## Phase 11 — Improvements
- asynchronous operations;
- reduced GUI blocking;
- reduced N+1 queries;
- better diagnostics;
- report worker isolation;
- Devis persistence;
- Client Account improvements;
- charges/analytics.

## Phase 12 — Finalization
- build/package through PyInstaller;
- branch-specific branding;
- stability verification;
- database connectivity troubleshooting.

---

# 12. Testing

## 12.1 Automated tests

Explicit test files:
- `tests/test_calculations.py`
- `tests/test_operations_table_decimal.py`
- `tests/test_qthread_lifetime.py`
- `tests/test_remote_table_worker.py`
- `tests/test_shutdown_subprocess.py`
- `tests/test_recent_changes_full.py`
- `tests/test_operation_summary.py`
- `tests/test_sync_coordinator.py`

A focused command:
`python -m unittest tests.test_recent_changes_full`

Reported result:
`Ran 6 tests`
`OK`

## 12.2 Critical stability pass

A later focused pass reported:
- 56 tests
- 19.5 seconds
- OK

Coverage:
- Sale Save stability;
- 100-cycle stress;
- close-during-save;
- duplicate-save;
- save-freeze responsiveness;
- QThread lifecycle;
- Client Account;
- reports;
- shutdown.

## 12.3 Broader suite

One point in project history reported approximately:
- 382 tests.

Another later project report referenced:
- 458 tests passed;
- 3 gated skips.

These counts are from different stages and should not be combined as one final suite result.

## 12.4 Real runtime testing

Required real workflow included:
- run `py main.py`;
- open Sales;
- Add Sale;
- fill Client/Product/Quantity/Unit Price/Remise/TVA/Notes;
- Save;
- verify responsiveness;
- verify sale appears once;
- verify stock;
- edit same Sale;
- save again;
- double-click Save;
- Historical Sale;
- close during Save;
- retry after validation/network failure;
- Add/Edit Import.

## 12.5 Stress tests

Requirements included:
- opening/closing Host and Client repeatedly;
- close during tab load;
- close during sync;
- close during thumbnail loading;
- heavy tabs 50 times;
- rapid tab switching for at least 10 minutes;
- repeated search/sort/refresh;
- many attachments;
- report/PDF/backup;
- network disconnect/reconnect;
- extended normal workflow.

## 12.6 Thread tests

Required:
- no QThread alive after shutdown;
- no access violations;
- no `QThreadStorage` failures;
- no worker GUI access;
- no MainThread DB/RPC blocking.

## 12.7 Data integrity tests

Required:
- no duplicate Sale;
- no double stock deduction;
- correct Historical Sale behavior;
- correct financial totals;
- Host/Client consistency.

## 12.8 What was NOT fully proven

The project history explicitly warns:
- isolated mocks do not prove real GUI behavior;
- previous agents incorrectly called Sale Save "fixed";
- real `py main.py` verification is mandatory.

Therefore:
**[CONFIRMED]** automated tests existed and many passed.  
**[UNCERTAIN]** absolute final real-runtime Sale Save reliability at the latest historical point.

---

# 13. Project Status

## 13.1 Implemented / strongly evidenced

- [CONFIRMED] PySide6 desktop application.
- [CONFIRMED] PostgreSQL authoritative database.
- [CONFIRMED] Host/Client LAN RPC architecture.
- [CONFIRMED] Products.
- [CONFIRMED] Services.
- [CONFIRMED] Clients.
- [CONFIRMED] Suppliers.
- [CONFIRMED] Sales.
- [CONFIRMED] Sale Items.
- [CONFIRMED] Imports.
- [CONFIRMED] Import Items.
- [CONFIRMED] Payments.
- [CONFIRMED] Client Account.
- [CONFIRMED] Attachments.
- [CONFIRMED] Reports/PDF.
- [CONFIRMED] Users/roles/permissions.
- [CONFIRMED] Profile/password protection.
- [CONFIRMED] Backups module.
- [CONFIRMED] Devis numbering/persistence architecture.
- [CONFIRMED] Dashboard.
- [CONFIRMED] Decimal-safe calculations.
- [CONFIRMED] Thread lifecycle improvements.
- [CONFIRMED] Report worker DB isolation.
- [CONFIRMED] Charges feature set.
- [CONFIRMED] Analytics/Net Profit feature set.
- [CONFIRMED] Windows packaging/build system.

## 13.2 Partially implemented / uncertain

- [UNCERTAIN] Final Bon de Livraison persistent numbering.
- [UNCERTAIN] Exact final PostgreSQL schema for every table.
- [UNCERTAIN] Final state of all UI refinements.
- [UNCERTAIN] Final real-world Sale Save reliability at the latest preserved point.
- [UNCERTAIN] Final report refresh API mismatch resolution.
- [UNCERTAIN] Final logging-rotation state.
- [UNCERTAIN] Exact role names/permission matrix.

## 13.3 Planned

Historically planned or requested:
- further Sale Save runtime verification;
- deeper stress verification;
- complete Bon de Livraison verification;
- exact PostgreSQL connectivity recovery after pg_hba.conf failure;
- continued UI refinements where needed.

## 13.4 Not implemented / intentionally disabled

- [CONFIRMED] SQLite replication/synchronization was intentionally disabled.
- [CONFIRMED] `ENABLE_SQLITE_CACHE = False`.
- [CONFIRMED] `ENABLE_INCREMENTAL_SYNC = False`.

Do not describe SQLite synchronization as a final feature.

---

# 14. Decisions and Alternatives

## Decision 1 — PostgreSQL as authoritative DB
**Alternative:** SQLite/local replication.  
**Choice:** PostgreSQL central authority.  
**Why:** consistent multi-user data and simpler source-of-truth model.  
**Consequence:** clients communicate with Host through RPC.

## Decision 2 — Disable SQLite cache/sync
**Alternative:** offline/local replication.  
**Choice:** disabled.  
**Why:** avoid synchronization complexity and inconsistent data.  
**Consequence:** Host remains authoritative.

## Decision 3 — Asynchronous heavy operations
**Alternative:** synchronous GUI-thread operations.  
**Choice:** workers/QThread.  
**Why:** prevent GUI freezes.  
**Consequence:** thread lifecycle and callback safety became critical.

## Decision 4 — Plain-data worker payloads
**Alternative:** worker reads widgets directly.  
**Choice:** build payload on GUI thread.  
**Why:** Qt widgets are GUI-thread objects.  
**Consequence:** clearer separation and safer threading.

## Decision 5 — Bound callbacks instead of lambdas
**Alternative:** lambda signal callback.  
**Choice:** QObject-bound methods/Slots.  
**Why:** GUI callback must execute safely on MainThread.  
**Consequence:** safer Qt threading.

## Decision 6 — Dedicated report worker DB connection
**Alternative:** reuse GUI psycopg2 connection.  
**Choice:** dedicated worker connection.  
**Why:** thread ownership safety.  
**Consequence:** report data work can remain asynchronous.

## Decision 7 — Prefetch catalogs
**Alternative:** one DB/RPC lookup per Sale row.  
**Choice:** prefetched in-memory catalog.  
**Why:** eliminate N+1 LAN/database calls.  
**Consequence:** faster and more stable Sale Save.

## Decision 8 — Persistent Devis reference
**Alternative:** transient/display-only document number.  
**Choice:** persistent `DE-YEAR-NUMBER`.  
**Why:** cross-screen/report consistency and concurrency safety.  
**Consequence:** reference must persist across restart/client mode.

## Decision 9 — Branch-specific company branding
**Alternative:** separate applications or runtime username-based branding.  
**Choice:** branches, same logic, different report branding.  
**Consequence:** `hazim` branch for LAMIBOIS.

---

# 15. Internship Learning / Skills

Only skills supported by the actual work should be claimed.

## Technical skills
- Python desktop application development.
- PySide6 / Qt GUI development.
- PostgreSQL database usage.
- SQL and database troubleshooting.
- LAN client/server architecture.
- RPC/API integration.
- PyInstaller packaging.
- Windows PowerShell build automation.
- HTML/CSS report templating.
- PDF generation integration.
- Git branch management.
- Logging and diagnostics.

## Programming/software engineering
- asynchronous programming;
- QThread lifecycle management;
- worker/GUI separation;
- transaction-oriented thinking;
- validation;
- CRUD;
- modular architecture;
- error handling;
- regression testing;
- performance optimization;
- avoiding N+1 calls.

## Database skills
- relational modeling;
- foreign keys;
- transactions;
- connection pooling;
- schema mismatch diagnosis;
- PostgreSQL configuration troubleshooting;
- backup architecture.

## Problem-solving
The project involved real debugging of:
- native Qt crashes;
- Windows access violations;
- database errors;
- GUI freezes;
- thread lifetime problems;
- report generation errors;
- performance issues;
- network/API mismatches;
- logging problems.

## Testing
- unit/regression tests;
- lifecycle tests;
- stress tests;
- subprocess tests;
- integration-style tests;
- real manual verification;
- interpreting logs and stack traces.

## Collaboration/process
- Working with supervisors and business requirements.
- Using AI coding agents/tools as development assistants.
- Reviewing generated changes rather than blindly accepting them.
- Reproducing bugs before claiming resolution.
- Maintaining branch-specific requirements.

Do not claim Agile/Scrum, formal UML, DevOps, CI/CD, or formal code review practices unless independently confirmed.

---

# 16. Important Conversation History

## 16.1 Project evolution
The project existed before the later stabilization work. A major part of the internship work involved improving and extending an existing application rather than creating every component from zero.

## 16.2 Stability became a major engineering objective
The project suffered severe GUI/threading failures:
- freezes;
- Not Responding;
- application closure;
- native Qt crashes;
- access violations.

This led to a dedicated stability effort.

## 16.3 AI-assisted development
The user repeatedly used AI coding agents such as OpenCode/Antigravity/Claude-oriented handoffs to inspect, patch and test the application.

A key process rule became:
**inspect → reproduce → diagnose → fix → focused test → factual report.**

Another key rule:
Do not say "fixed" based only on code inspection or isolated mocks.

## 16.4 Two-company strategy
The original company was LAMIDAP.

A second branch, `hazim`, was prepared for LAMIBOIS:
- same application;
- same business logic;
- different report branding.

LAMIBOIS:
- Company: LAMIBOIS
- Phone: 0661135570
- Email: Lamibois1@gmail.com
- Address: Hararin Sidi driss 35, Tanger 90000

Requirements:
- use LAMIBOIS logo;
- remove old LAMIDAP company data;
- preserve client/supplier ICE where appropriate;
- company name must not derive from profile username;
- enlarge logo;
- remove duplicate company text under logo;
- preserve report layout/data.

This branch strategy is a deployment/customization concern and should not be confused with the internship company's core business logic.

## 16.5 VAT / branding variation
A prior branch/workflow involved removing TVA from the Lamibois version and changing price calculation to:
`price × quantity`

Report labels containing TVA were to be removed.

However, the broader current handoff also preserves standard HT/TVA/TTC calculations for the core sales logic. Therefore:
- [CONFIRMED] there was a Lamibois-specific TVA removal requirement.
- [CONFIRMED] standard sales formulas existed in the general application.
- [UNCERTAIN] which exact branch/version should be represented as the final internship version.

## 16.6 Generated Devis evidence
A real generated Devis document showed:
- LAMIDAP SARL branding;
- `DE-2026-1`;
- date;
- client;
- Total Remise;
- Total HT;
- TVA;
- Net à payer / Total TTC;
- item rows;
- legal/bank footer.

This is evidence that report generation was operational at that point.

## 16.7 Diagnostics and evidence-driven development
The project accumulated logs containing:
- RPC durations;
- build IDs;
- thread names;
- memory;
- query counts;
- report generation times;
- errors and stack traces.

This was used to diagnose real performance and stability problems.

---

# 17. Unknown / Uncertain Information

## [UNKNOWN]
- Exact official internship department/service.
- Exact internship dates.
- Exact official project title in French.
- Exact original business process before PyLocalInventory.
- Exact number of application users in production.
- Exact final PostgreSQL database name.
- Complete final PostgreSQL table schema.
- Complete final PostgreSQL column list and data types.
- Exact role names and complete permission matrix.
- Exact final UI screenshots/design specifications.
- Formal MCD/MLD/ERD/UML diagrams.
- Exact final formula for every Analytics/Net Profit metric.
- Exact final Charges fields.
- Exact final Bon de Livraison implementation status.
- Exact final production deployment environment.
- Exact PostgreSQL server machine used in production.
- Exact final resolution of the PostgreSQL 18 `pg_hba.conf` blocker.
- Exact final status of the real Sale Save freeze after the last preserved handoff.

## [UNCERTAIN]
- Whether all report-generation backends were actually exercised or only configured.
- Whether custom log rotation was fully deployed in the final build.
- Whether every planned stress test was completed on both Host and Client.
- Whether all 458 tests belonged to the final identical code revision.
- Whether the Lamibois TVA-removal branch represents the exact version used for the internship report.
- Whether persistent BL numbering was completed.

## [LIKELY]
- The project was intended as an operational internal business-management tool rather than a public SaaS.
- PostgreSQL + LAN RPC was selected to allow several computers to share one central database.
- The project architecture resembles a layered desktop client/server system with model/core/database/UI separation.
- The project used transactions for critical Sale/Import persistence.

---

# 18. MASTER PROJECT CONTEXT

## Identity

```yaml
project_name: PyLocalInventory
project_type: Windows desktop inventory and business management application
company: LAMIDAP
professional_supervisor: Marouan Laghmich
internship_duration: 2 months
internship_department: UNKNOWN
internship_exact_dates: UNKNOWN
```

## Core purpose

```yaml
purpose:
  - inventory management
  - product/service management
  - client management
  - supplier management
  - sales management
  - imports management
  - payments and client balances
  - quotations/devis
  - delivery notes
  - invoices/receipts
  - reports/PDF
  - attachments
  - backups
  - user/role permissions
  - financial analytics
  - charges and recurring charges
```

## Architecture

```yaml
architecture:
  type: desktop client/server
  platform: Windows
  gui: PySide6/Qt
  authoritative_database: PostgreSQL
  networking: LAN HTTP/JSON RPC/API
  host:
    database: PostgreSQL
    server: core/network/server.py
  client:
    rpc_client: core/network/client.py
  feature_flags:
    ENABLE_SQLITE_CACHE: false
    ENABLE_INCREMENTAL_SYNC: false
  packaging: PyInstaller
  build: build_windows.ps1
```

## Main modules

```yaml
modules:
  - Home
  - Products
  - Services
  - Clients
  - Suppliers
  - Sales
  - Imports
  - Reports
  - Payments
  - Attachments
  - Backups
  - Users/Roles/Permissions
  - Profiles/Connection Configuration
  - Charges
  - Analytics
```

## Main data entities

```yaml
entities:
  - Products
  - Services
  - Clients
  - Suppliers
  - Sales
  - Sales_Items
  - Imports
  - Import_Items
  - Payments
  - Reports
  - Attachments
  - Users/Roles/Permissions
  - charge_categories
  - charge_recurring_templates
  - charges
```

## Critical business rules

```yaml
sales:
  subtotal: sum(quantity * unit_price)
  total_ht: subtotal - remise
  tva: total_ht * vat_rate
  total_ttc: total_ht + tva

normal_sale:
  stock_effect: decrease

historical_sale:
  stock_effect: none

edit_sale:
  duplicate_sale: forbidden
  double_stock_deduction: forbidden
  totals: recalculate

payment_edit:
  selected_payment_only: true
  stock_effect: none
  duplicate_payment: forbidden

devis:
  format: DE-YEAR-NUMBER
  persistent: true
  unique: true
  concurrency_safe: true
```

## Security

```yaml
security:
  profile_password:
    file: core/password.py
    mechanism: Fernet encryption
  network:
    users: true
    roles: true
    permissions: true
    enforcement: server-side
```

## Threading rules

```yaml
threading:
  worker_reads_widgets: false
  gui_access_from_worker: false
  gui_callbacks: MainThread
  terminate: forbidden_for_normal_flow
  cancellation: cooperative
  request_interruption: true
  quit: true
  clear_thread_refs_before_finished: false
  duplicate_workers: forbidden
  stale_results: ignored
```

## Important files

```yaml
core:
  - core/database.py
  - core/calculations.py
  - core/password.py
  - core/user_manager.py
  - core/pg_config.py
  - core/pg_backup.py
  - core/memory_utils.py
  - core/diagnostics.py
  - core/network/server.py
  - core/network/client.py
  - core/network/protocol.py
  - core/sync.py

ui:
  - ui/main_window.py
  - ui/dialogs/reports_dialog.py
  - ui/dialogs/client_details_dialog.py
  - ui/dialogs/edit_dialogs/base_operation_dialog.py
  - ui/dialogs/edit_dialogs/sale_dialog.py
  - ui/widgets/operations_table.py
  - ui/tabs/home_tab.py
  - ui/tabs/base_tab.py

tests:
  - tests/test_calculations.py
  - tests/test_operations_table_decimal.py
  - tests/test_qthread_lifetime.py
  - tests/test_remote_table_worker.py
  - tests/test_shutdown_subprocess.py
  - tests/test_recent_changes_full.py
  - tests/test_operation_summary.py
  - tests/test_sync_coordinator.py
```

## Main technical achievements

```yaml
achievements:
  - safer Decimal parsing
  - Sale Save asynchronous architecture
  - safer QThread lifecycle
  - MainThread GUI callback enforcement
  - reduced N+1 queries/RPC calls
  - dedicated report worker database connection
  - report/PDF generation
  - Client Account and payment editing
  - persistent Devis references
  - attachments
  - LAN RPC permissions
  - dashboard analytics
  - Charges and recurring charges
  - Net Profit analytics
  - diagnostics and logging improvements
  - Windows packaging
```

## Major historical bugs

```yaml
bugs:
  - Sale Save freeze / Not Responding
  - QThread destroyed while running
  - QThreadStorage errors
  - Fatal Python Aborted
  - Windows access violation
  - Internal C++ object already deleted
  - decimal.InvalidOperation
  - Decimal ConversionSyntax
  - Imports UndefinedColumn si.information
  - shutdown logger NameError
  - OperationsTable load_data nonexistent
  - report resource_path undefined
  - report worker failed signal missing
  - report qty key error
  - raw report placeholders
  - application closing during print
  - thread-unsafe Qt print
  - false watchdog stalls
  - RAM shown as 0.0MB
  - mojibake
  - log rotation blocked by stale processes
  - remote Reports get_items API mismatch
```

## Testing evidence

```yaml
focused_stability_pass:
  tests: 56
  duration_seconds: 19.5
  result: OK

another_focused_suite:
  tests: 6
  result: OK

historical_broad_suite:
  approximate_tests: 382

later_reported_full_discovery:
  passed: 458
  gated_skips: 3

important_caveat:
  real_manual_runtime_verification is required
  automated mocks do not prove GUI/runtime stability
```

## Current/last preserved blocker

```yaml
blocker:
  component: PostgreSQL 18
  error: "FATAL: could not load .../pg_hba.conf"
  host: 192.168.100.11
  port: 5432
  status: unresolved_in_last_handoff
  next_step:
    - inspect PostgreSQL server logs
    - identify exact pg_hba parsing/loading failure
    - make smallest safe fix
    - retest pg_isready
    - retest psql
    - retest PyLocalInventory
```

## Critical reporting instruction

When another AI uses this context to write the internship report:

1. Treat PostgreSQL as the final authoritative database architecture.
2. Do not describe SQLite replication as a final feature.
3. Do not invent the missing schema.
4. Do not claim the exact internship dates unless the user supplies them.
5. Do not claim formal UML/MCD/MLD diagrams existed unless supplied.
6. Do not claim every requested feature was implemented.
7. Clearly distinguish historical bugs from final state.
8. Describe Sale Save carefully because automated stability tests and real manual reports were not always consistent.
9. Use the exact names of important files/classes/tables where known.
10. Present the project as a real engineering application involving GUI, database, LAN networking, asynchronous execution, business rules, reporting and testing.
11. If discussing LAMIBOIS, explain that it was a second-company branding branch and not necessarily the same final internship branch.
12. If a fact is absent here, label it UNKNOWN rather than inventing it.

---

# Source/Evidence Notes

The strongest preserved evidence came from:
- `PYLOCALINVENTORY_COMPLETE_LLM_HANDOFF_2026-08-10.md`
- `PYLOCALINVENTORY_CLAUDE_SALE_FREEZE_HANDOFF.md`
- project log excerpts (`Pasted text(20260806-100923).txt`)
- project code/XML excerpts containing PySide6, PostgreSQL, profile and report implementation details
- generated Devis PDF evidence
- prior project discussions recorded in conversation memory.

This document intentionally does not use unrelated projects (ASTRA, GoMorocco, mailing automation, etc.) as evidence for PyLocalInventory.
