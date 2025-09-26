<div align="center">

# PyLocalInventory

Offline, local-first inventory & sales desktop application with multi-profile support, dark UI, backups, and optional password protection. No server. No cloud. Your data stays on your machine.

</div>

## 1. Highlights
- 100% offline (SQLite) – zero setup, zero network
- Multiple business profiles (each isolated in its own folder & database)
- Optional password protection (per profile) + encrypted validation phrase (note: only a validation phrase is encrypted; database content is plain SQLite)
- Products, Clients, Suppliers, Sales and Imports (with line items & snapshots)
- Automatic name snapshots in operations (keeps history even if base records are edited/deleted)
- Integrated backup & restore (timestamped folders you can copy anywhere)
- Multilingual UI: English / Français / Español (switch at runtime)
- Dark, compact, keyboard-friendly interface
- Portable: copy the whole `profiles/<YourProfile>` folder to move/share

## 2. Quick Start
### Prerequisites
Python 3.10+ (recommended 3.11+). A virtual environment is strongly suggested.

### Install & Run
```bash
python -m venv .venv
# Activate on Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt  # If provided; else install pyside6 & cryptography
python main.py
```

If no `requirements.txt` exists, minimal dependencies:
```bash
pip install PySide6 cryptography
```

When the app starts you'll see either:
1. A welcome screen (no profile selected yet), or
2. A password screen (if the last used profile has a password), or
3. The main tabbed interface (if an open, non‑protected profile is active).

## 3. Profiles (Your Data Containers)
Each profile = one business/company context.

Folder structure example:
```
profiles/
  WoodCraft_Demo/
    WoodCraft_Demo.db
    config.json
    preview.png (optional logo/thumbnail)
    backups/ (auto-created when you create backups)
    images/   (your own added images if any)
```

### Creating a Profile
Menu > Profiles → Create (fill company name, optional info, pick an image). A database file is created automatically when first opened.

### Switching Profiles
Menu > Profiles → select another profile. The UI reloads accordingly. Your last selection persists across restarts.

### Duplicating / Deleting
Provided via the Profiles dialog. Duplication copies base entities (Products, Clients, Suppliers) into a fresh database; operational history (Sales/Imports) is not copied (clean starting point).

## 4. Password Protection
Profiles start UNLOCKED (no password) unless a password was already set.

To set or change a password:
1. Open profile (unlocked state)
2. Use the password/encryption option (if exposed) OR first-time protection flow (if implemented in your build)
3. A validation phrase is stored encrypted; on login it's decrypted to verify correctness.

Behavior:
- Wrong password → red border feedback
- Correct password → main tabs load
- Logout (Menu > Log Out) returns to password or profile selection

Important: Only the validation phrase is encrypted in config; database tables themselves are plain SQLite. For full at-rest encryption use external disk encryption or adapt the data layer.

## 5. Main Interface
Tabs (localized with emojis):
- Home: High-level overview / dashboard
- Products: Create/update product records (name, pricing, quantity, etc.)
- Clients: Manage customer identities
- Suppliers: Manage provider identities
- Sales: Record sales operations with line items (detached snapshots of product names & client name)
- Imports: Record stock/import operations with item lines & supplier snapshot

Line item tables automatically keep product_name snapshots so even if a product is later renamed or deleted, historic records remain readable.

## 6. Working With Data
### Adding Items
Use the + / Add button inside each tab (dialog opens). Required fields are validated. 

### Editing
Select a row → Edit (or double-click depending on UX) → Save.

### Deleting
Deletes the entity. For Products, existing historical operation items retain the stored product_name while product_id references are nullified safely.

### Searching & Ordering
Product tab includes search (username/name) and ordering (price, quantity, alphabetical, etc.). Other tabs follow a similar pattern (depending on current build).

## 7. Sales & Imports (Operations)
1. Create a Sale/Import (parent record)
2. Add line items (quantities, pricing or cost fields)
3. Totals aggregate automatically (if implemented in base class)
4. Deleting a Sale/Import cascades to its line items (ON DELETE CASCADE)

Snapshots: client_name / supplier_name and product_name columns are stored so history survives later edits.

## 8. Backups
Menu > Backups opens the Backups Manager.

Features:
- Create backup (suggested timestamp name)
- Restore selected backup (replaces current profile files except the backups directory)
- Rename / Duplicate / Delete backups

Each backup is a folder under: `profiles/<ProfileName>/backups/<BackupTimestamp>/`

Manual safety copy: You can just copy any backup folder elsewhere (USB, external drive, etc.).

Restore Warning: Restoring overwrites current profile data. Make a new backup first if unsure.

## 9. Language Switching
Menu > Language → choose English / Français / Español. The interface reloads instantly. Your choice is saved and reused next time.

## 10. Portability & Migration
To move a profile to another machine:
1. Close the application (ensures SQLite file is released)
2. Copy the whole `profiles/<ProfileName>` folder
3. Paste it into the `profiles` directory on the target machine
4. Launch the app → Profile appears automatically

To clone the entire application with data, copy the whole project folder (or just keep code separate and only move the `profiles` directory).

## 11. Troubleshooting
| Issue | Possible Cause | Fix |
|-------|----------------|-----|
| Profile not appearing | Folder name mismatch or missing `config.json` | Ensure folder contains valid `config.json` |
| Cannot delete a product | Product referenced in operations (legacy FK) | App now nullifies references; restart & retry |
| Wrong password always | Typo or config corruption | Recreate profile if password truly lost |
| DB locked errors (rare) | Open file handle during backup/restore | Wait a moment & retry; ensure only one app instance |

Logs / console output (when launched from terminal) will display table creation, migrations, and refresh steps – useful for diagnosing.

## 12. Data Safety Notes
- Back up regularly before large deletes
- Snapshots keep historic text, but deleting a Product removes its live record
- No cloud sync; use your own storage strategy (external drive, OS backups)

## 13. Extending (Optional Note)
Even though this README focuses on end users, advanced users can inspect the `classes/` folder to see parameter-driven models and extend new entities following the same pattern.

## 14. License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0).

You are free to run, study, share, and modify the software under the terms of the GPL. Any distributed modified version must also be GPL-licensed. See the `LICENSE` file for the full text.

## 15. Disclaimer (No Warranty)
PyLocalInventory is provided "AS IS", without any express or implied warranties – including but not limited to merchantability, fitness for a particular purpose, non‑infringement, data accuracy, or uninterrupted operation. You use the application entirely at your own risk.

By using this software you agree that:
- You are solely responsible for creating and verifying backups of your data.
- The authors/contributors are not liable for data loss, corruption, business interruption, or any consequential, incidental, or indirect damages.
- The built‑in password feature does NOT encrypt the database contents; it only gates access within the UI and stores an encrypted validation phrase. For true at‑rest protection use full-disk / OS-level encryption or adapt the storage layer.
- This tool is not certified accounting or compliance software. Always verify exported/derived figures before financial or legal use.

The full legal disclaimer is already included in the GPL‑3.0 license text (see the "NO WARRANTY" sections). This README section is a plain‑language summary only.

## 16. Attribution & Thanks
Built with Python, PySide6, and SQLite. Thanks to the open-source ecosystem.
AI Assistance: Portions of ideation, refactoring suggestions, and documentation wording were assisted by large language models (Anthropic Claude Sonnet 4 and OpenAI GPT-5). All architectural and approach choices, code integration, testing, and final verification were performed manually.

---
Enjoy using PyLocalInventory. Keep control of your data.