"""Wrapper around the supplied Anumati crypto jar. Requires JDK 21+."""
import json, subprocess, os
from pathlib import Path
JAR = os.getenv("CRYPTO_JAR", str(Path(__file__).parent / "fiu-crypto-lib.jar"))

def genkey():
    out = subprocess.run(["java", "-jar", JAR, "--genkey"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)

def decrypt_getdata(getdata_path, private_key_pem_path=None, our_nonce=None):
    """UAT escrow: uatKeyMaterial sits at the ROOT of the response (verified), so
       no key args are needed. Production: pass the key + nonce for that fetch."""
    cmd = ["java", "-jar", JAR, "--getdata", str(getdata_path)]
    if private_key_pem_path: cmd += ["--private-key", str(private_key_pem_path)]
    if our_nonce: cmd += ["--our-nonce", our_nonce]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout)
