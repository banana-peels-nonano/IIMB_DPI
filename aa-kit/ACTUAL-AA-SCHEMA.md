# ACTUAL AA SCHEMA

Derived from `decrypted.json` — the real UAT response, not documentation.

**Sessions returned: 7**

- session 0: fipId=`ACME-FIP` masked=`XXXXXXXX9333` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 1: fipId=`ACME-FIP` masked=`XXXXXXXX9335` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 2: fipId=`ACME-FIP` masked=`XXXXXXXX9960` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 3: fipId=`ACME-FIP` masked=`XXXXXXXX9950` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 4: fipId=`ACME-FIP` masked=`XXXXXXXX9648` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 5: fipId=`ACME-FIP` masked=`XXXXXXXX9334` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']
- session 6: fipId=`ACME-FIP` masked=`XXXXXXXX9741` keys=['data', 'fipId', 'linkRefNumber', 'maskedAccNumber']

| Field path | Types seen | Sample values |
|---|---|---|
| `[]` | len_7×1 | — |
| `[].data` | str×7 | `<?xml version="1.0" encoding="UTF-8" sta`, `<?xml version="1.0" encoding="UTF-8" sta`, `<?xml version="1.0" encoding="UTF-8" sta` |
| `[].fipId` | str×7 | `ACME-FIP`, `ACME-FIP`, `ACME-FIP` |
| `[].linkRefNumber` | str×7 | `e2b2110f-5f4d-426e-b818-49136c30b53c`, `4c7b78eb-2b64-4a97-81ec-3f7386bdab29`, `06ce96cb-5531-4d6a-8353-555da0e5c687` |
| `[].maskedAccNumber` | str×7 | `XXXXXXXX9333`, `XXXXXXXX9335`, `XXXXXXXX9960` |