# License System Test Implementation

## Overview

This document describes the simple local license system added to PyLocalInventory for testing purposes. The system uses cryptographically signed license files to control application access on the Main PC.

## What Was Added

### New Files

1. **`core/machine_id.py`** - Generates a stable machine identifier for license binding
2. **`core/license.py`** - Complete license management (creation, signing, verification, validation)
3. **`tests/test_license.py`** - Comprehensive test suite for the license system
4. **`docs/licensing-test.md`** - This documentation

### Modified Files

1. **`main.py`** - Added license check at application startup

## How the License Works

### License File Format (`license.dat`)

The license is stored as a JSON file with the following structure:

```json
{
  "license": {
    "company_name": "ABC Company",
    "machine_id": "a1b2c3d4e5f6...",
    "expires_at": "2027-09-01",
    "issued_at": "2024-01-15",
    "license_type": "TRIAL",
    "grace_period_days": 7
  },
  "signature": "base64_encoded_ecdsa_signature"
}
```

### License Fields

| Field | Description |
|-------|-------------|
| `company_name` | Company name for display |
| `machine_id` | 32-char hex machine identifier (SHA-256 of hardware components) |
| `expires_at` | Expiration date in ISO format (YYYY-MM-DD) |
| `issued_at` | Issue date in ISO format (YYYY-MM-DD) |
| `license_type` | License tier: TRIAL, STANDARD, PROFESSIONAL, ENTERPRISE |
| `grace_period_days` | Days after expiry before blocking (default: 7) |
| `signature` | ECDSA-SHA256 signature of the license data |

### Machine ID Generation

The machine ID is generated from multiple hardware sources for stability:

1. **Windows MachineGuid** (registry) - Primary, most stable
2. **Windows ProductId** (registry) - Fallback
3. **MAC addresses** - All non-virtual network interfaces
4. **CPU ID** - Processor identifier
5. **Motherboard serial** - If available
6. **Primary disk serial** - If available

Components are combined, sorted, and hashed with SHA-256 to produce a 32-character hex string. The ID is cached to a file for consistency.

### Cryptographic Signing

- **Algorithm**: ECDSA with P-256 curve (secp256r1) and SHA-256
- **Private key**: Used only by developer to create licenses
- **Public key**: Embedded in application for verification
- **Signature**: Covers all license fields (canonical JSON)

This ensures licenses cannot be forged or modified without detection.

## License File Location

Default path: `%LOCALAPPDATA%\PyLocalInventory\license.dat`

Example: `C:\Users\username\AppData\Local\PyLocalInventory\license.dat`

The application searches for the license at this location on startup.

## How to Create a Test License

### Using the Test Helpers (for development)

```python
from core.license import create_test_license, save_license_file
from core.runtime_paths import user_data_root
import os

# Create a valid license for 365 days on current machine
license_file, private_key, public_key = create_test_license(
    company_name="My Test Company",
    days_valid=365,
    license_type="TRIAL",
    grace_period_days=7
)

# Save to default location
save_license_file(license_file)
```

### Using the CLI (manual testing)

Create a script `create_license.py`:

```python
#!/usr/bin/env python
"""Create a license file for testing."""
from core.license import create_test_license, save_license_file, public_key_to_pem, private_key_to_pem

# Generate license
license_file, private_key, public_key = create_test_license(
    company_name="ABC Corp",
    days_valid=365,
    license_type="STANDARD",
    grace_period_days=7
)

# Save license
save_license_file(license_file)
print(f"License saved to default location")

# Print keys for reference (save these securely!)
print(f"Private key (KEEP SECRET):\n{private_key_to_pem(private_key)}")
print(f"Public key (embed in app):\n{public_key_to_pem(public_key)}")
```

Run with: `python create_license.py`

### Creating an Expired License for Testing

```python
from core.license import create_expired_test_license, save_license_file

# Create license expired 10 days ago
license_file, private_key, public_key = create_expired_test_license(
    company_name="ABC Corp",
    days_expired=10,
    grace_period_days=7
)

save_license_file(license_file)
```

## How to Test Different License Scenarios

### 1. Valid License → Application Works

```python
from core.license import create_test_license, save_license_file

license_file, _, _ = create_test_license(company_name="Test Corp", days_valid=365)
save_license_file(license_file)
# Run app: python main.py  → Should start normally
```

### 2. Expired License → Application Blocked

```python
from core.license import create_expired_test_license, save_license_file

license_file, _, _ = create_expired_test_license(company_name="Test Corp", days_expired=10)
save_license_file(license_file)
# Run app: python main.py  → Should show error and exit
```

### 3. Invalid License (Wrong Signature) → Application Blocked

```python
import json
from core.license import create_test_license, save_license_file

license_file, _, _ = create_test_license(company_name="Test Corp", days_valid=365)
save_license_file(license_file)

# Corrupt the signature
with open("license.dat", 'r') as f:
    data = json.load(f)
data["signature"] = data["signature"][:-1] + "x"
with open("license.dat", 'w') as f:
    json.dump(data, f)

# Run app: python main.py  → Should show "invalid signature" error
```

### 4. License for Another Machine ID → Application Blocked

```python
from core.license import create_test_license, save_license_file

# Create license for a fake machine ID
license_file, _, _ = create_test_license(
    company_name="Test Corp",
    days_valid=365,
    machine_id="different_machine_id_123456789012"
)
save_license_file(license_file)

# Run app on current machine → Should show "different machine" error
```

### 5. Modified License → Application Blocked

```python
import json
from core.license import create_test_license, save_license_file

license_file, _, _ = create_test_license(company_name="Test Corp", days_valid=365)
save_license_file(license_file)

# Modify company name in license file
with open("license.dat", 'r') as f:
    data = json.load(f)
data["license"]["company_name"] = "Hacked Corp"
with open("license.dat", 'w') as f:
    json.dump(data, f)

# Run app: python main.py  → Should show "invalid signature" error
```

### 6. Valid License → LAN Server Still Works

The license check only runs on the Main PC at startup. Once the application is running:

- LAN server starts normally if enabled
- Client PCs connect normally
- No license check on client PCs

### 7. Expired License → Database NOT Deleted/Modified

The license check happens **before** any database connection:

```python
# In main.py:
# 1. Check license (exits if invalid)
# 2. Create QApplication
# 3. Create MainWindow
# 4. MainWindow creates Database and connects
```

If license is invalid, the application exits at step 1. The database is never touched.

## Running the Tests

### All License Tests

```bash
python -m pytest tests/test_license.py -v
```

### Specific Test Classes

```bash
# Test license data structures
python -m pytest tests/test_license.py::TestLicenseData -v

# Test signing and verification
python -m pytest tests/test_license.py::TestLicenseSigning -v

# Test validation logic
python -m pytest tests/test_license.py::TestLicenseValidation -v

# Test file I/O
python -m pytest tests/test_license.py::TestLicenseFileIO -v

# Integration tests
python -m pytest tests/test_license.py::TestLicenseIntegration -v
```

### Using unittest Directly

```bash
python -m unittest tests.test_license -v
```

## What We Should Implement Later (Future Work)

The current implementation is a **local-only test system**. For production, the following should be added:

### Online License Activation

```
Main PC
   ↓
HTTPS
   ↓
License Server
   ↓
ACTIVE / SUSPENDED / EXPIRED
```

### Features for Production

1. **Online License Activation**
   - Main PC contacts license server on first run
   - Server validates license key and binds to machine ID
   - Server returns signed license file

2. **Remote Suspension**
   - License server can revoke/suspend licenses
   - Main PC checks in periodically (heartbeat)
   - Immediate effect on all connected clients

3. **Subscription Expiration**
   - Automatic expiration based on subscription period
   - Renewal workflow through license server

4. **Payment Status Integration**
   - Link license status to payment gateway
   - Auto-suspend on failed payments

5. **Admin Dashboard**
   - Web interface for license management
   - View all activated machines
   - Issue/revoke licenses

6. **Offline Grace Period**
   - Allow continued operation during temporary network outages
   - Configurable offline tolerance (e.g., 30 days)

7. **Better Clock Manipulation Protection**
   - Detect system time changes
   - Use trusted time sources (NTP, license server)
   - Hardware-based time tracking

8. **Hardware Fingerprinting Improvements**
   - TPM-based machine identity (Windows)
   - More robust hardware binding
   - Handle hardware upgrades gracefully

9. **License File Encryption**
   - Encrypt sensitive license fields
   - Prevent casual inspection/modification

10. **Audit Logging**
    - Log all license checks and violations
    - Tamper-evident logs

## Implementation Notes

### Easy to Remove/Replace

The license system is designed to be easily removable:

1. All license logic is in `core/license.py` and `core/machine_id.py`
2. Only `main.py` imports and calls the license check
3. No database changes required
4. No UI changes required
5. Can be disabled by removing the `_check_license()` call in `main.py`

### Current Limitations (Test Branch)

- Uses a hardcoded default public key (replace with your own)
- No online verification
- No heartbeat/refresh mechanism
- Grace period is client-side only (can be bypassed by clock change)
- Machine ID may change on major hardware changes

### Security Considerations

- The embedded public key can be extracted from the application
- For real deployment, generate your own keypair and embed the public key
- Consider code obfuscation for the verification logic
- The license file is not encrypted (only signed)
- System clock manipulation can bypass expiration checks

## Quick Reference

### Default Public Key (Replace for Production)

The default public key in `core/license.py` is a placeholder. Generate your own:

```python
from core.license import generate_keypair, public_key_to_pem, private_key_to_pem

private_key, public_key = generate_keypair()
print("PRIVATE KEY (keep secret):")
print(private_key_to_pem(private_key))
print("\nPUBLIC KEY (embed in app):")
print(public_key_to_pem(public_key))
```

Then update `DEFAULT_PUBLIC_KEY_PEM` in `core/license.py` with your public key.

### License Status Codes

| Status | Meaning | Application Behavior |
|--------|---------|---------------------|
| `VALID` | License OK | Normal operation |
| `GRACE_PERIOD` | Expired but within grace | Normal operation (warning logged) |
| `EXPIRED` | License expired | Block startup, show error |
| `INVALID_SIGNATURE` | Signature mismatch | Block startup, show error |
| `MACHINE_ID_MISMATCH` | Wrong machine | Block startup, show error |
| `NOT_FOUND` | No license file | Block startup, show error |
| `INVALID_FORMAT` | Corrupt license file | Block startup, show error |

### Environment Variables

No environment variables required. All paths use `%LOCALAPPDATA%\PyLocalInventory\`.