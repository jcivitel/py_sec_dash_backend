# Sec-Dash-Backend - CrowdSec Data Analysis Dashboard

A Python FastAPI-based backend solution for managing, analyzing, and visualizing CrowdSec security data with real-time decision streaming and geographic threat intelligence.

## Features

- 🔐 **CrowdSec Integration**: Real-time decision streaming and API integration for security alerts
- 📊 **Data Analysis**: Comprehensive statistics on attacks, top-attacking IPs, and attack scenarios
- 🌍 **GeoIP Intelligence**: Geographic localization of attack sources with country-level insights
- 🗄️ **Redis Caching**: High-performance in-memory caching for optimized data retrieval
- 🔒 **API Security**: API-Key based authentication with rate limiting
- ⚡ **Async-First**: Fully asynchronous processing with FastAPI and httpx
- 📈 **REST API**: Modern REST endpoints for frontend integration
- 🌐 **CORS Support**: Cross-origin resource sharing for frontend applications

## Project Structure

```
py_sec_dash_backend/
├── app/
│   ├── __init__.py
│   ├── config.py              # Configuration and environment variables
│   ├── crowdsec_client.py     # CrowdSec API and stream client
│   ├── redis_client.py        # Redis caching client
│   └── api/
│       ├── __init__.py
│       ├── health.py          # Health check endpoints
│       ├── alerts.py          # Alert management and statistics API
│       └── country.py         # Country-level threat intelligence API
├── main.py                    # FastAPI application entry point
├── .env                       # Environment variables (do not commit!)
├── .env.example               # Example .env configuration
├── requirements.txt           # Python dependencies
├── LICENSE                    # MIT License
└── README.md                  # This file
```

## Installation

### 1. Activate Virtual Environment

```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Or install individually:
```bash
pip install fastapi uvicorn httpx python-dotenv slowapi redis
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

**Required Variables:**
- `CROWDSEC_HOST`: CrowdSec API URL (e.g., http://localhost:8080)
- `CROWDSEC_API_KEY`: API key for CrowdSec authentication
- `API_PORT`: Port for FastAPI server (default: 8000)
- `API_KEY`: API key for backend authentication (default: generated)
- `REDIS_HOST`: Redis host for caching (default: localhost)
- `REDIS_PORT`: Redis port (default: 6379)
- `REDIS_DB`: Redis database number (default: 0)

### 4. Start the Server

```bash
python main.py
```

Server runs at: **http://localhost:8000**

API Documentation: **http://localhost:8000/docs**

## API Endpoints

All endpoints are available at `http://localhost:8000`

### Health Check
- `GET /health` - Service health status
- `GET /health/redis` - Redis connectivity check

All application endpoints live under `/api/v1`.

### Decisions & Alerts
- `GET /api/v1/decisions` - Attacks currently running (last 20 seconds)
- `GET /api/v1/decisions/history?limit=&offset=` - Paginated history over the
  rolling 24 h window, newest first. `limit` max. 1000.

### Country Intelligence
- `GET /api/v1/country` - Attack counts per country over the last 24 h, plus
  metadata (`total_attacks`, `unique_countries`, `attacks_per_hour`)

### Timeline
- `GET /api/v1/timeline` - Attacks per hour for the last 24 hours (24 entries,
  oldest first)

See [API.md](API.md) for full request and response formats.

## CrowdSec Integration

This backend integrates with CrowdSec in two ways:

### 1. REST API Client
Fetches alert and decision data from CrowdSec API endpoints.

### 2. Real-Time Stream Listener
Connects to CrowdSec decision stream for real-time updates. The stream listener runs as a background thread and automatically processes incoming decisions.

**Configuration:**
- `CROWDSEC_HOST`: Main CrowdSec API endpoint
- `CROWDSEC_API_KEY`: Authentication key for CrowdSec

## Storage Model

Redis is the only datastore. Every attack is written **once** and expires after
24 hours; aggregates are maintained on write rather than computed from the raw
events, so read cost stays constant as data accumulates.

| Key | Type | Contents |
|-----|------|----------|
| `sec:attacks` | ZSET | member = decision id, score = unix time (index over the 24 h window) |
| `sec:attack:{id}` | STRING | JSON payload of one attack, TTL 24 h |
| `sec:hour:{h}:countries` | ZSET | country code → count for hour `h` |
| `sec:hour:{h}:total` | STRING | attack count for hour `h` |
| `sec:countries:24h` | ZSET | 15 s cache of the union over the 24 hourly buckets |

Hourly buckets expire via `EXPIREAT` 25 hours after their hour ends, so no
background job is needed. The attack index is trimmed at most once a minute on
write; payloads clean themselves up through their own TTL.

Writes go out in a single pipeline, so one incoming attack costs one round trip.

## Tests

The test suite runs against a real Redis instance:

```bash
# Start a throwaway Redis
docker run -d --rm --name sec_dash_redis_test -p 63790:6379 redis:8-alpine

# Install dev dependencies and run
pip install -r requirements-dev.txt
REDIS_HOST=localhost REDIS_PORT=63790 REDIS_DB=15 pytest tests/ -q
```

`REDIS_DB` is flushed before every test - point it at a scratch database, never
at the production one.

Alternatively `docker compose -f docker-compose.dev.yml up --build` starts the
backend together with its own Redis.

## Logging

Logging is configured using Python's standard logging module. Logs are output to:
- Console (stdout)
- Log files (if configured)

Adjust log level in `main.py` by changing the `logging.basicConfig` level.

## Deployment

### Docker Compose (Recommended)

The easiest way to run the entire stack (backend + Redis):

```bash
# Copy environment variables
cp .env.example .env

# Edit .env with your CrowdSec settings
nano .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f sec-dash-backend
```

The backend will be available at `http://localhost:8000` and Redis at `localhost:6379`.

### Docker (Manual)

Build the image:
```bash
docker build -t sec-dash-backend .
```

Run with existing Redis:
```bash
docker run -p 8000:8000 \
  -e CROWDSEC_HOST=http://crowdsec:8080 \
  -e CROWDSEC_API_KEY=your_key \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  sec-dash-backend
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start Redis (if not running)
redis-server

# Run the application
python main.py
```

Server will be available at `http://localhost:8000`

## Troubleshooting

### Redis Connection Failed
1. Is Redis running and accessible at `REDIS_HOST:REDIS_PORT`?
2. Check firewall rules and network connectivity

### CrowdSec Connection Failed
1. Is CrowdSec API running at `CROWDSEC_HOST`?
2. Is the `CROWDSEC_API_KEY` valid?
3. Check network connectivity and firewall settings

### Stream Listener Not Receiving Updates
1. Verify CrowdSec is configured to enable decision stream
2. Check that `CROWDSEC_API_KEY` has appropriate permissions
3. Review logs for stream connection errors

## License

MIT

## Support

For questions or issues:
- Open an issue in the repository
- Consult the CrowdSec documentation: https://docs.crowdsec.net
- Check FastAPI documentation: https://fastapi.tiangolo.com
