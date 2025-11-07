# Sectacho - CrowdSec Data Analysis Backend

Eine Python FastAPI-basierte Backend-Lösung zur Verwaltung, Analyse und Visualisierung von CrowdSec-Sicherheitsdaten.

## Features

- 🔐 **CrowdSec Integration**: Direkte Anbindung an CrowdSec API für Echtzeitwarnungen
- 📊 **Datenanalyse**: Statistiken über Angriffe, Top-IPs und Szenarien
- 🌍 **GeoIP-Lokalisierung**: Geografische Lokalisierung von Angriffsquellen
- 🗄️ **PostgreSQL**: Robuste relationale Datenbank für Datenspeicherung
- 🔒 **API-Authentifizierung**: API-Key basierte Sicherheit
- ⚡ **Asynchron**: Vollständig asynchrone Verarbeitung mit FastAPI
- 📈 **REST API**: Moderne REST-Schnittstellen für Frontend-Integration

## Projektstruktur

```
py_sectacho/
├── app/
│   ├── __init__.py
│   ├── config.py              # Konfiguration und Umgebungsvariablen
│   ├── database.py            # SQLAlchemy Setup
│   ├── models.py              # Datenmodelle (Alert, Remediation, etc.)
│   ├── schemas.py             # Pydantic Schemas für Request/Response
│   ├── auth.py                # API-Key Authentifizierung
│   ├── crowdsec_client.py     # CrowdSec API Client
│   ├── utils.py               # Utility-Funktionen (GeoIP, etc.)
│   └── api/
│       ├── __init__.py
│       ├── health.py          # Health Check Endpunkte
│       ├── alerts.py          # Alert Management API
│       └── statistics.py      # Statistik API
├── alembic/                   # Datenbankmigration (Alembic)
├── main.py                    # FastAPI Entry Point
├── .env                       # Umgebungsvariablen (nicht commiten!)
├── .env.example               # Beispiel .env Datei
├── requirements.txt           # Python Dependencies
└── README.md                  # Diese Datei
```

## Installation

### 1. Virtuelle Umgebung aktivieren

```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Dependencies installieren

```bash
pip install -r requirements.txt
```

Oder einzeln:
```bash
pip install fastapi uvicorn httpx sqlalchemy psycopg2-binary python-dotenv pydantic python-jose passlib python-multipart slowapi geoip2
```

### 3. PostgreSQL Datenbank einrichten

Stelle sicher, dass PostgreSQL läuft und erstelle die Datenbank:

```sql
CREATE DATABASE sectacho;
```

### 4. Umgebungsvariablen konfigurieren

Kopiere `.env.example` zu `.env` und konfiguriere:

```bash
cp .env.example .env
```

**Wichtige Variablen:**
- `DATABASE_HOST`: PostgreSQL Host (default: localhost)
- `DATABASE_PORT`: PostgreSQL Port (default: 5432)
- `DATABASE_NAME`: Datenbankname (default: sectacho)
- `DATABASE_USER`: PostgreSQL Benutzer
- `DATABASE_PASSWORD`: PostgreSQL Passwort
- `CROWDSEC_HOST`: CrowdSec API URL (z.B. http://localhost:8080)
- `CROWDSEC_API_KEY`: CrowdSec API Key für Authentifizierung
- `SECRET_KEY`: Geheimer Schlüssel für Token-Signierung
- `API_PORT`: Port für FastAPI Server (default: 8000)

### 5. Datenbanktabellen initialisieren

```bash
python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"
```

### 6. Server starten

```bash
python main.py
```

Server läuft dann unter: **http://localhost:8000**

API Documentation: **http://localhost:8000/docs**

## API Endpunkte

### Health Check
- `GET /api/v1/health` - Service Status
- `GET /api/v1/health/db` - Datenbank Status

### Alerts
- `GET /api/v1/alerts` - Alle Warnungen abrufen
  - Query Parameter: `skip`, `limit`, `ip`, `severity`
- `GET /api/v1/alerts/{alert_id}` - Einzelne Warnung
- `POST /api/v1/alerts/refresh` - Warnungen von CrowdSec aktualisieren
- `GET /api/v1/alerts/stats/hourly` - Statistiken der letzten 24 Stunden

### Statistiken
- `GET /api/v1/statistics/summary` - Zusammenfassung aller Warnungen
- `GET /api/v1/statistics/top-ips` - Top Angriffs-IPs
- `GET /api/v1/statistics/top-scenarios` - Häufigste Angriff Szenarien
- `GET /api/v1/statistics/daily` - Tägliche Statistiken

## Authentifizierung

Sende den API-Key im Header:
```bash
curl -H "X-API-Key: your_api_key" http://localhost:8000/api/v1/alerts
```

## GeoIP Datenbank

Für GeoIP-Lokalisierung wird die kostenlose GeoLite2-City Datenbank von MaxMind verwendet:

1. Registriere dich kostenlos: https://www.maxmind.com/en/geolite2
2. Lade `GeoLite2-City.mmdb` herunter
3. Platziere die Datei im Projektroot

## Datenbankmigration mit Alembic

```bash
# Migration erstellen
alembic revision --autogenerate -m "Description"

# Alle Migrationen anwenden
alembic upgrade head

# Zu vorheriger Version zurück
alembic downgrade -1
```

## Roadmap (implementiert)

- ✅ Projektsetup mit FastAPI
- ✅ CrowdSec API Integration mit httpx
- ✅ PostgreSQL Verbindung mit SQLAlchemy
- ✅ REST API Endpunkte (/alerts, /statistics)
- ✅ Datenmodelle und Validierung (Pydantic)
- ⚙️ API-Key Authentifizierung (vorhanden, noch nicht aktiviert)
- ⚙️ Rate-Limiting (slowapi installiert, noch nicht im main.py)
- ⏳ WebSocket für Echtzeit-Updates
- ⏳ Automatische Datenbank-Backups
- ⏳ Logging und Monitoring

## Logs

Logs werden mit Python logging konfiguriert. Für Production:
```python
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
```

## Deployment

### Docker
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

### mit Gunicorn (Production)
```bash
pip install gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

## Troubleshooting

### Datenbankverbindung schlägt fehl
1. PostgreSQL läuft?
2. `.env` Variablen korrekt?
3. Datenbankbenutzer hat Permissions?

### CrowdSec Verbindung schlägt fehl
1. CrowdSec API läuft? (`CROWDSEC_HOST`)
2. API-Key gültig? (`CROWDSEC_API_KEY`)
3. Firewall blockiert Verbindung?

## Lizenz

MIT

## Support

Bei Fragen oder Problemen:
- Öffne ein Issue im Repository
- Konsultiere die CrowdSec Dokumentation: https://docs.crowdsec.net
