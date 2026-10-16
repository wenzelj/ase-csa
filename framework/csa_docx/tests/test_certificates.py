"""Certificates: machine certificate issuer and expiry, other certificates, private roots."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings  # noqa: E402

MY = """
Subject       : CN=00175Affb406
Issuer        : CN=Cisco Manufacturing CA, O=Cisco Systems
NotBefore     : 18-Nov-15 18:40:18
NotAfter      : 18-Nov-25 18:50:18
HasPrivateKey : False

Subject       : CN=HOSTAA101.internal.example.au
Issuer        : CN=Example Online Issuing CA, DC=internal
NotBefore     : 20-Nov-25 11:27:27
NotAfter      : 20-Nov-26 11:27:27
HasPrivateKey : True

Subject       : CN=CLIUSR
Issuer        : CN=CLIUSR
NotAfter      : 20-May-27 12:47:38
HasPrivateKey : True
"""
ROOT = """
Subject    : CN=DigiCert Global Root CA, OU=www.digicert.com, O=DigiCert Inc, C=US
Issuer     : CN=DigiCert Global Root CA, OU=www.digicert.com, O=DigiCert Inc, C=US

Subject    : CN=Example OT Root CA
Issuer     : CN=Example OT Root CA

Subject    : CN=ClusInfraCert_20250817_031137003
Issuer     : CN=ClusInfraCert_20250817_031137003

Subject    : OU=Copyright (c) 1997 Microsoft Corp., OU=Microsoft Corporation, CN=Microsoft Root Authority
Issuer     : OU=Copyright (c) 1997 Microsoft Corp., OU=Microsoft Corporation, CN=Microsoft Root Authority
"""


def test_certificate_settings():
    cap = lambda f, t: {"HOSTAA101": {"folder": "X_discovery_HOSTAA101_20260709T000000Z", "fname": f, "start": 1, "text": t}}  # noqa: E731
    got = {r["attribute"]: r["value"] for r in host_settings.cert_settings(
        {"my": cap("68_certificates_localmachine_my.txt", MY), "root": cap("69_certificates_localmachine_root.txt", ROOT)})}
    assert got["cert.machine"] == "Example Online Issuing CA, expires 20/11/2026"
    assert got["cert.other"] == "00175Affb406 from Cisco Manufacturing CA, expired 18/11/2025, CLIUSR (failover cluster, self-signed)"
    assert got["cert.private_roots"] == "Example OT Root CA"
