# TLS Zertifikate für CrowdSec

Dieser Ordner enthält die TLS-Zertifikate für die sichere Kommunikation mit der CrowdSec Local API.

## Erforderliche Dateien

Platziere die folgenden drei Dateien in diesem Ordner:

1. **client.crt** - Client-Zertifikat
   - Das Zertifikat zur Identifikation gegenüber CrowdSec

2. **client.key** - Privater Schlüssel
   - Der private Schlüssel für das Klient-Zertifikat

3. **ca.crt** - CA-Zertifikat
   - Das Root-Zertifikat zur Verifizierung des CrowdSec-Servers

## Anleitung zur Erlangung der Zertifikate

Siehe CrowdSec Dokumentation: https://docs.crowdsec.net/docs/local_api/tls_auth#using-the-certificates

### Von CrowdSec generieren:

Deine CrowdSec-Installation sollte diese Zertifikate bereits generiert haben. Sie befinden sich normalerweise unter:
- Linux/Mac: `/etc/crowdsec/bouncers/`
- Windows: `C:\ProgramData\CrowdSec\bouncers\`

## Konfiguration

Die Pfade sind in `.env` Datei konfiguriert:

```
CROWDSEC_TLS_CERT=tls/client.crt
CROWDSEC_TLS_KEY=tls/client.key
CROWDSEC_TLS_CA=tls/ca.crt
```

## Sicherheit

⚠️ Diese Dateien enthalten sensitive Informationen!
- Sie sind in `.gitignore` aufgelistet und sollten NICHT in die Versionskontrolle committed werden
- Restrict Dateiberechtigungen: `chmod 600 *.crt *.key` (auf Linux/Mac)
- Speichere Backups an einem sicheren Ort
