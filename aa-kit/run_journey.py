import argparse, json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import anumati_client as ac
from decrypt import decrypt_getdata

CAP = Path(__file__).parent / "captures"

def latest(pattern):
    xs = sorted(CAP.glob(pattern))
    return xs[-1] if xs else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mobile"); ap.add_argument("--collect", action="store_true")
    ap.add_argument("--purpose", default="102"); ap.add_argument("--fetch-type", default="PERIODIC")
    ap.add_argument("--fi-types", default="DEPOSIT")
    a = ap.parse_args()

    if not os.getenv("ANUMATI_CLIENT_SECRET"):
        sys.exit("ANUMATI_CLIENT_SECRET not set - put it in .env")

    if a.mobile:
        r = ac.start_consent(a.mobile, a.purpose, a.fetch_type, a.fi_types.split(","))
        print(json.dumps({k: v for k, v in r.items() if k != "redirectUrl"}, indent=2))
        print("\nOPEN THIS, choose ACME Bank, OTP 812093:\n", r["redirectUrl"])
        (CAP / "last_module_reference.txt").write_text(r.get("moduleReference", ""))
        return

    if a.collect:
        p = latest("*_data-ready_payload.json")
        if not p: sys.exit("no data-ready callback captured yet")
        dr = json.loads(p.read_text())
        print(f"using callback {p.name}: moduleReference={dr.get('moduleReference')} "
              f"sessionCount={dr.get('sessionCount')} expiresAt={dr.get('expiresAt')}")
        _, raw_path = ac.fetch_data(dr["id"], dr["secret"])
        out = decrypt_getdata(raw_path)
        (CAP / "decrypted.json").write_text(json.dumps(out, indent=2))
        print(f"decrypted {len(out)} session(s) -> captures/decrypted.json")
        return
    ap.print_help()

if __name__ == "__main__":
    main()
