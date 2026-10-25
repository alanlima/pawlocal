"""Load pinned AWS CDN artwork in memory; keep only non-AWS glyphs local."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen

CDN_BASE = (
    "https://cdn.jsdelivr.net/gh/phergoualch/aws-icons@"
    "ec5b8422f1a48621bff6eebd1d4a270cf51dc70d/public/icons/services/"
)
# Original AWS geometry, verified against the 31 July 2026 official package.
# Each tuple binds the local builder's asset name to a CDN path and exact bytes.
AWS_ASSETS = {
    "Arch_Amazon-CloudFront_64.svg": (
        "networking-content-delivery/amazon-cloudfront.svg",
        "664919982792a69058077eaf39240afd320bbcbd082d36a9148184ec32708cd5",
    ),
    "Arch_Amazon-Simple-Storage-Service_64.svg": (
        "storage/amazon-simple-storage-service.svg",
        "b92c5101cc6565dd12df37655802279f8fba0c719279f62f93106d26750b36c6",
    ),
    "Arch_Amazon-Cognito_64.svg": (
        "security-identity/amazon-cognito.svg",
        "cf9c55baa325d5d07aea0054115b1b24d68c1d7e046a4f8a360ccdefbba507e9",
    ),
    "Arch_Amazon-Lightsail_64.svg": (
        "compute/amazon-lightsail.svg",
        "29299e75d9dc489c416ca66a2653027d2f61f68540c7cd0c9c9181fb549ca79a",
    ),
    "Arch_Amazon-Aurora_64.svg": (
        "databases/amazon-aurora.svg",
        "0cbdccc29da3a25d4954dee4ac7afa4c2ae53dca9238bc4d995c3692e905ed4b",
    ),
    "Arch_AWS-Identity-and-Access-Management_64.svg": (
        "security-identity/aws-identity-and-access-management.svg",
        "3135793557c065d0481a3985ccc0574b36278d56a2e2c5d59107d0d28f51b827",
    ),
    "Arch_AWS-Systems-Manager_64.svg": (
        "management-tools/aws-systems-manager.svg",
        "2b8720205ebaa0ab034c512b5e09e15d72bdc808688257e70b58e5a8d0b4d466",
    ),
    "Arch_AWS-Lambda_64.svg": (
        "compute/aws-lambda.svg",
        "5818c80cd8e7d08891a2492c7694f472ca914fb3a99d9ef8e597db0b37ad7f13",
    ),
}
LOCAL_GLYPHS = {"github.svg", "terraform.svg", "grafana.svg", "react.svg", "docker.svg"}


@lru_cache(maxsize=len(AWS_ASSETS) + len(LOCAL_GLYPHS))
def load_icon(name: str) -> bytes:
    """Return verified AWS bytes or a named local brand glyph; never write a cache."""
    if name in AWS_ASSETS:
        path, expected_hash = AWS_ASSETS[name]
        with urlopen(CDN_BASE + path, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"AWS icon CDN returned HTTP {response.status}: {name}")
            data = response.read()
        if sha256(data).hexdigest() != expected_hash:
            raise RuntimeError(f"AWS icon integrity check failed: {name}")
        return data
    if name in LOCAL_GLYPHS:
        return (Path(__file__).resolve().parent / "icons" / name).read_bytes()
    raise ValueError(f"Unknown architecture icon: {name}")
