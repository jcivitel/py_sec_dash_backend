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

### Decisions & Alerts
- `GET /decisions` - Get the latest decisions from CrowdSec stream listener
  - Returns: Latest decisions stored in Redis with full decision data

### Country Intelligence
- `GET /country` - Get country-level threat data
  - Returns: Decision counts and attack statistics grouped by country

## CrowdSec Integration

This backend integrates with CrowdSec in two ways:

### 1. REST API Client
Fetches alert and decision data from CrowdSec API endpoints.

### 2. Real-Time Stream Listener
Connects to CrowdSec decision stream for real-time updates. The stream listener runs as a background thread and automatically processes incoming decisions.

**Configuration:**
- `CROWDSEC_HOST`: Main CrowdSec API endpoint
- `CROWDSEC_API_KEY`: Authentication key for CrowdSec

## Caching Strategy

The application uses Redis for caching to optimize data retrieval:

- **Alert summaries**: Cached for 5 minutes
- **Country statistics**: Cached for 10 minutes
- **Top data (IPs, scenarios)**: Cached for 15 minutes

Cache is automatically invalidated when new alerts are processed from CrowdSec stream.

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
