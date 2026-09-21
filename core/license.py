"""
License system for PyLocalInventory.

Provides signed license files with verification, expiration checking,
and machine ID binding.
"""
import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

from core.runtime_paths import user_data_root
from core.machine_id import generate_machine_id, get_cached_machine_id

logger = logging.getLogger(__name__)


class LicenseStatus(Enum):
    """License validation status."""
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    MACHINE_ID_MISMATCH = "MACHINE_ID_MISMATCH"
    INVALID_FORMAT = "INVALID_FORMAT"
    NOT_FOUND = "NOT_FOUND"
    GRACE_PERIOD = "GRACE_PERIOD"


@dataclass
class LicenseData:
    """License data structure."""
    company_name: str
    machine_id: str
    expires_at: str
    issued_at: str
    license_type: str = "TRIAL"
    grace_period_days: int = 7

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'LicenseData':
        return cls(**data)

    def is_expired(self, grace_days: int = 0) -> bool:
        """Check if license is expired (considering grace period)."""
        exp = datetime.fromisoformat(self.expires_at)
        now = datetime.now()
        if grace_days > 0:
            exp += timedelta(days=grace_days)
        return now > exp

    def days_until_expiry(self) -> int:
        """Get days until expiry (negative if expired)."""
        exp = datetime.fromisoformat(self.expires_at)
        delta = exp - datetime.now()
        return delta.days


@dataclass
class LicenseFile:
    """Complete license file structure."""
    license: LicenseData
    signature: str

    def to_dict(self) -> dict:
        return {
            "license": self.license.to_dict(),
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LicenseFile':
        return cls(
            license=LicenseData.from_dict(data["license"]),
            signature=data["signature"],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> 'LicenseFile':
        return cls.from_dict(json.loads(json_str))


DEFAULT_LICENSE_PATH = os.path.join(user_data_root(), "license.dat")
DEFAULT_GRACE_PERIOD_DAYS = 7


# Embedded public key for license verification (replace with your actual key)
# This is a test key - in production, generate your own keypair
DEFAULT_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEFY4CzbQT6oZIChNvb5Zj1VZQ63Fn
U5xq2YbErczwSnxSBa2GfKN0E9aweEO2LShLaE44jMIXiJr4JVl1Gxer6A==
-----END PUBLIC KEY-----"""

# Corresponding private key for the default public key (TEST ONLY - not secure!)
# In production, NEVER embed private keys. This is only for test license creation.
DEFAULT_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg73cjjHgsk38ZpaPQ
rxlKOARDCUhl3pCZsGtAE1Q/BhmhRANCAAQVjgLNtBPqhkgKE29vlmPVVlDrcWdT
nGrZhsStzPBKfFIFrYZ8o3QT1rB4Q7YtKEtoTjiMwheImvglWXUbF6vo
-----END PRIVATE KEY-----"""


def load_default_private_key() -> ec.EllipticCurvePrivateKey:
    """Load the default test private key."""
    key = serialization.load_pem_private_key(
        DEFAULT_PRIVATE_KEY_PEM.encode('utf-8'),
        password=None,
    )
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("Private key is not an ECDSA key")
    return key


def load_public_key(pem: str | None = None) -> ec.EllipticCurvePublicKey:
    """Load ECDSA public key from PEM string."""
    key_pem = (pem or DEFAULT_PUBLIC_KEY_PEM).encode('utf-8')
    key = serialization.load_pem_public_key(key_pem)
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("Public key is not an ECDSA key")
    return key


def generate_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """Generate a new ECDSA keypair for license signing."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


def private_key_to_pem(private_key: ec.EllipticCurvePrivateKey) -> str:
    """Serialize private key to PEM string."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')


def public_key_to_pem(public_key: ec.EllipticCurvePublicKey) -> str:
    """Serialize public key to PEM string."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('utf-8')


def sign_license(license_data: LicenseData, private_key: ec.EllipticCurvePrivateKey) -> str:
    """
    Create a digital signature for license data.

    Args:
        license_data: License data to sign
        private_key: ECDSA private key

    Returns:
        Base64-encoded signature
    """
    payload = json.dumps(license_data.to_dict(), sort_keys=True, separators=(',', ':')).encode('utf-8')
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode('utf-8')


def verify_signature(license_data: LicenseData, signature_b64: str, public_key: ec.EllipticCurvePublicKey) -> bool:
    """
    Verify a license signature.

    Args:
        license_data: License data to verify
        signature_b64: Base64-encoded signature
        public_key: ECDSA public key

    Returns:
        True if signature is valid
    """
    try:
        payload = json.dumps(license_data.to_dict(), sort_keys=True, separators=(',', ':')).encode('utf-8')
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def create_license(
    company_name: str,
    machine_id: str,
    expires_at: str,
    private_key: ec.EllipticCurvePrivateKey,
    license_type: str = "TRIAL",
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    issued_at: str | None = None,
) -> LicenseFile:
    """
    Create a signed license file.

    Args:
        company_name: Company name
        machine_id: Target machine ID
        expires_at: Expiration date in ISO format (YYYY-MM-DD)
        private_key: ECDSA private key for signing
        license_type: License type (TRIAL, STANDARD, PROFESSIONAL, ENTERPRISE)
        grace_period_days: Grace period in days
        issued_at: Issue date in ISO format (defaults to now)

    Returns:
        Signed LicenseFile object
    """
    if issued_at is None:
        issued_at = datetime.now().date().isoformat()

    license_data = LicenseData(
        company_name=company_name,
        machine_id=machine_id,
        expires_at=expires_at,
        issued_at=issued_at,
        license_type=license_type,
        grace_period_days=grace_period_days,
    )

    signature = sign_license(license_data, private_key)
    return LicenseFile(license=license_data, signature=signature)


def load_license_file(path: str = DEFAULT_LICENSE_PATH) -> Optional[LicenseFile]:
    """
    Load license from file.

    Args:
        path: Path to license file

    Returns:
        LicenseFile object or None if not found/invalid
    """
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return LicenseFile.from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug("Failed to load license file: %s", e)
        return None


def save_license_file(license_file: LicenseFile, path: str = DEFAULT_LICENSE_PATH) -> bool:
    """
    Save license to file.

    Args:
        license_file: LicenseFile to save
        path: Path to license file

    Returns:
        True if saved successfully
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(license_file.to_dict(), f, indent=2)
        return True
    except Exception as e:
        logger.error("Failed to save license file: %s", e)
        return False


def validate_license(
    license_file: LicenseFile | None,
    public_key: ec.EllipticCurvePublicKey | None = None,
    machine_id: str | None = None,
    grace_period_days: int | None = None,
) -> tuple[LicenseStatus, Optional[LicenseData]]:
    """
    Validate a license file.

    Args:
        license_file: LicenseFile to validate
        public_key: ECDSA public key (uses default if None)
        machine_id: Machine ID to check against (uses current machine if None)
        grace_period_days: Override grace period (uses license value if None)

    Returns:
        Tuple of (LicenseStatus, LicenseData or None)
    """
    if license_file is None:
        return LicenseStatus.NOT_FOUND, None

    if public_key is None:
        public_key = load_public_key()

    if machine_id is None:
        machine_id = get_cached_machine_id()

    if grace_period_days is None:
        grace_period_days = license_file.license.grace_period_days

    if not verify_signature(license_file.license, license_file.signature, public_key):
        logger.warning("License signature verification failed")
        return LicenseStatus.INVALID_SIGNATURE, license_file.license

    if license_file.license.machine_id != machine_id:
        logger.warning("License machine ID mismatch: expected %s, got %s",
                       machine_id, license_file.license.machine_id)
        return LicenseStatus.MACHINE_ID_MISMATCH, license_file.license

    # Check if license is expired without any grace period
    expired_without_grace = license_file.license.is_expired(0)
    
    # Check if license is expired with the effective grace period
    expired_with_grace = license_file.license.is_expired(grace_period_days)

    if expired_with_grace:
        # License is expired even with grace period -> EXPIRED
        logger.warning("License expired on %s", license_file.license.expires_at)
        return LicenseStatus.EXPIRED, license_file.license
    elif expired_without_grace and grace_period_days > 0:
        # License is expired without grace but not with grace -> GRACE_PERIOD
        logger.info("License expired but within grace period")
        return LicenseStatus.GRACE_PERIOD, license_file.license

    return LicenseStatus.VALID, license_file.license


def check_license(
    license_path: str = DEFAULT_LICENSE_PATH,
    public_key_pem: str | None = None,
    machine_id: str | None = None,
) -> tuple[LicenseStatus, Optional[LicenseData]]:
    """
    Complete license check: load and validate.

    Args:
        license_path: Path to license file
        public_key_pem: Public key PEM string (uses default if None)
        machine_id: Machine ID to check against (uses current machine if None)

    Returns:
        Tuple of (LicenseStatus, LicenseData or None)
    """
    license_file = load_license_file(license_path)
    if license_file is None:
        return LicenseStatus.NOT_FOUND, None

    public_key = load_public_key(public_key_pem) if public_key_pem else load_public_key()
    return validate_license(license_file, public_key, machine_id)


def get_license_status_message(status: LicenseStatus, license_data: LicenseData | None = None) -> str:
    """Get user-friendly message for license status."""
    messages = {
        LicenseStatus.VALID: "License is valid and active.",
        LicenseStatus.EXPIRED: f"License has expired on {license_data.expires_at if license_data else 'unknown date'}.",
        LicenseStatus.INVALID_SIGNATURE: "License is invalid (signature verification failed).",
        LicenseStatus.MACHINE_ID_MISMATCH: "License is for a different machine.",
        LicenseStatus.INVALID_FORMAT: "License file format is invalid.",
        LicenseStatus.NOT_FOUND: "No license file found.",
        LicenseStatus.GRACE_PERIOD: f"License expired on {license_data.expires_at if license_data else 'unknown date'} but is within grace period.",
    }
    return messages.get(status, "Unknown license status.")


def create_test_license(
    company_name: str = "Test Company",
    days_valid: int = 365,
    machine_id: str | None = None,
    license_type: str = "TRIAL",
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    use_default_keys: bool = True,
) -> tuple[LicenseFile, ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """
    Create a test license for development/testing.

    Args:
        company_name: Company name
        days_valid: Days until expiration
        machine_id: Target machine ID (uses current machine if None)
        license_type: License type
        grace_period_days: Grace period in days
        use_default_keys: If True, use embedded default keys (license will verify with default public key).
                          If False, generate a new keypair (license will NOT verify with default public key).

    Returns:
        Tuple of (LicenseFile, private_key, public_key)
    """
    if machine_id is None:
        machine_id = generate_machine_id()

    expires_at = (datetime.now() + timedelta(days=days_valid)).date().isoformat()
    
    if use_default_keys:
        private_key = load_default_private_key()
        public_key = load_public_key()
    else:
        private_key, public_key = generate_keypair()
    
    license_file = create_license(
        company_name=company_name,
        machine_id=machine_id,
        expires_at=expires_at,
        private_key=private_key,
        license_type=license_type,
        grace_period_days=grace_period_days,
    )
    return license_file, private_key, public_key


def create_expired_test_license(
    company_name: str = "Test Company",
    days_expired: int = 1,
    machine_id: str | None = None,
    license_type: str = "TRIAL",
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    use_default_keys: bool = True,
) -> tuple[LicenseFile, ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """
    Create an expired test license.

    Args:
        company_name: Company name
        days_expired: Days since expiration
        machine_id: Target machine ID (uses current machine if None)
        license_type: License type
        grace_period_days: Grace period in days
        use_default_keys: If True, use embedded default keys (license will verify with default public key).
                          If False, generate a new keypair (license will NOT verify with default public key).

    Returns:
        Tuple of (LicenseFile, private_key, public_key)
    """
    if machine_id is None:
        machine_id = generate_machine_id()

    expires_at = (datetime.now() - timedelta(days=days_expired)).date().isoformat()
    
    if use_default_keys:
        private_key = load_default_private_key()
        public_key = load_public_key()
    else:
        private_key, public_key = generate_keypair()
    
    license_file = create_license(
        company_name=company_name,
        machine_id=machine_id,
        expires_at=expires_at,
        private_key=private_key,
        license_type=license_type,
        grace_period_days=grace_period_days,
    )
    return license_file, private_key, public_key