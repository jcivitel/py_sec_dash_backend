# Security Dashboard - API Documentation

## Overview
The Security Dashboard connects to a CrowdSec-based backend that streams real-time cyber attack data. This document specifies the expected API responses and data formats.

## Base URL Configuration
Edit `lib/services/api_service.dart` to configure the backend URL:

```dart
// Local development
static const String baseUrl = 'http://localhost:8000/api';

// Docker/Kubernetes
static const String baseUrl = 'http://192.168.81.151:30300/api';

// Production
static const String baseUrl = 'https://api.yourdomain.com/api';
```

---

## Endpoints

### 1. **GET /v1/decisions**
Fetches the latest cyber attack decisions from the CrowdSec stream.

#### Response Format
```json
{
  "status": "success",
  "decision": [
    {
      "unique_decision_id_1": {
        "latitude": 45.5,
        "longitude": 10.2,
        "cn": "IT",
        "timestamp": "2025-01-05T14:30:00+01:00"
      }
    },
    {
      "unique_decision_id_2": {
        "latitude": 40.7,
        "longitude": -74.0,
        "cn": "US",
        "timestamp": "2025-01-05T14:30:15+01:00"
      }
    }
  ]
}
```

#### Response Fields
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| status | string | "success" or "error" | ✅ Yes |
| decision | array | Array of decision objects | ✅ Yes |
| decision[].id | string | Unique decision ID (used as key) | ✅ Yes |
| decision[].latitude | number | Attack source latitude (-90 to 90) | ✅ Yes |
| decision[].longitude | number | Attack source longitude (-180 to 180) | ✅ Yes |
| decision[].cn | string | ISO 3166-1 alpha-2 country code (e.g., "US", "CN", "DE") | ✅ Yes |
| decision[].timestamp | string | ISO 8601 timestamp with timezone | ✅ Yes |

#### Validation Rules
- **Invalid Coordinates**: Decisions with latitude=0 AND longitude=0 are filtered out
- **Timestamp Format**: Must be ISO 8601 format (e.g., `2025-01-05T14:30:00+01:00`)
- **Country Code**: Must be valid ISO 3166-1 alpha-2 code

#### Example Request
```bash
curl -X GET http://192.168.81.151:30300/api/v1/decisions
```

#### Response Time
- Expected: < 5 seconds (configured timeout)
- Should return latest 20 decisions

---

### 2. **GET /v1/country**
Fetches aggregated attack counts by country with metadata for KPI calculations.

#### Response Format
```json
{
  "status": "success",
  "metadata": {
    "total_attacks": 2847,
    "unique_countries": 47,
    "attacks_per_hour": 119
  },
  "countries": [
    {"CN": 145},
    {"US": 98},
    {"RU": 67},
    {"DE": 34},
    {"IT": 28},
    {"FR": 19},
    {"GB": 15},
    {"JP": 12},
    {"CA": 11},
    {"AU": 8}
  ]
}
```

#### Response Fields
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| status | string | "success" or "error" | ✅ Yes |
| metadata | object | Aggregated statistics for KPI cards | ✅ Yes |
| metadata.total_attacks | number | Attacks within the rolling 24 h window | ✅ Yes |
| metadata.unique_countries | number | Distinct attacking countries within the 24 h window | ✅ Yes |
| metadata.attacks_per_hour | number | Attacks in the **last 60 minutes** (current rate, not the daily average) | ✅ Yes |
| countries | array | Array of country objects sorted by count (descending) | ✅ Yes |
| countries[].countryCode | string | ISO country code key (e.g., "CN") | ✅ Yes |
| countries[].count | number | Number of attacks from this country | ✅ Yes |

#### Important Notes
- **Metadata is sent only once** with the `/country` endpoint
- **Backend calculates** `total_attacks`, `unique_countries`, `attacks_per_hour`
- **Frontend caches** these values and updates only on new `/country` response
- **Frontend responsibility**: Calculate Attacks/Hour based on timestamp history if more precision needed

#### Sorting
- Results **MUST** be sorted by count in **descending order** (highest first)
- The dashboard displays the top 10 countries

#### Example Request
```bash
curl -X GET http://192.168.81.151:30300/api/v1/country
```

---

### 3. **GET /v1/timeline**

Attacks per hour for the last 24 hours, oldest entry first. Backed by
pre-aggregated hourly counters, so the cost is constant regardless of how many
attacks are stored.

#### Response Format
```json
{
  "status": "success",
  "timeline": [
    { "hour_start": "2026-08-23T16:00:00+02:00", "hours_ago": 23, "count": 43 },
    { "hour_start": "2026-08-23T17:00:00+02:00", "hours_ago": 22, "count": 54 }
  ],
  "total": 1047
}
```

#### Response Fields
| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| timeline | array | Exactly 24 entries, oldest first |
| timeline[].hour_start | string | ISO 8601 start of the hour, in the configured timezone |
| timeline[].hours_ago | number | Distance from the current hour (23 ... 0) |
| timeline[].count | number | Attacks recorded in that hour |
| total | number | Sum over all 24 entries |

#### Why this exists
The dashboard previously reconstructed the hourly histogram by paging through
`/v1/decisions/history` — thousands of raw events for a 24-value chart. This
endpoint replaces that with a single `MGET`.

#### Example Request
```bash
curl -X GET http://192.168.81.151:30300/api/v1/timeline
```

---

## Data Flow & Caching

### Backend Architecture
```
CrowdSec → Stream Listener → Redis Cache → API Endpoints
```

### Storage Model
Every attack is stored **once** and expires after 24 hours. Aggregates are
maintained on write, so read cost does not grow with the amount of stored data.

| Key | Type | Contents |
|-----|------|----------|
| `sec:attacks` | ZSET | member = decision id, score = unix time. Index over the 24 h window. |
| `sec:attack:{id}` | STRING | JSON payload of one attack, TTL 24 h (self-expiring). |
| `sec:hour:{h}:countries` | ZSET | member = country code, score = count within hour `h`. |
| `sec:hour:{h}:total` | STRING | Number of attacks within hour `h`. |
| `sec:countries:24h` | ZSET | Short-lived cache (15 s) of the union over the 24 hourly buckets. |

`h` is the full unix hour (`timestamp // 3600`). Hourly buckets expire via
`EXPIREAT` 25 hours after their hour ends.

**Query cost**
- `/v1/decisions` — `ZREVRANGEBYSCORE` over the last 20 s + one `MGET`
- `/v1/country` — `ZUNIONSTORE` over 24 small buckets (cached 15 s) + two `ZCOUNT`
- `/v1/timeline` — a single `MGET` of 24 counters
- `/v1/decisions/history` — `ZREVRANGE` page + one `MGET`

None of these read the raw event set in full.

- **Update Frequency**: Dashboard polls `/v1/decisions` every 1.5 seconds

---

## Frontend Implementation Details

### Decision Model Parsing
The frontend expects decisions as a dictionary where the key is the unique ID:

```dart
// Example: What the backend sends
{
  "abc123def456": {
    "latitude": 45.5,
    "longitude": 10.2,
    "cn": "IT",
    "timestamp": "2025-01-05T14:30:00+01:00"
  }
}

// Frontend parses it like this:
final id = json.keys.first;  // "abc123def456"
final data = json[id];       // The inner object
```

### Timestamp Handling
- **Timezone**: Backend should send timestamps in the server's configured timezone
- **Parsing**: Frontend parses ISO 8601 format automatically
- **Fallback**: If timestamp is missing, frontend uses current device time

### Country Code Mapping
Frontend supports the following country code to name mapping:

```dart
const countryNames = {
  'US': 'USA',
  'CN': 'China',
  'RU': 'Russland',
  'IN': 'Indien',
  'BR': 'Brasilien',
  'JP': 'Japan',
  'DE': 'Deutschland',
  'FR': 'Frankreich',
  'GB': 'Großbritannien',
  'KR': 'Südkorea',
  'CA': 'Kanada',
  'AU': 'Australien',
  'NL': 'Niederlande',
  'CH': 'Schweiz',
  'SE': 'Schweden',
  'SG': 'Singapur',
  'HK': 'Hongkong',
  'MX': 'Mexiko',
  'IT': 'Italien',
  'ES': 'Spanien',
};
```

For unlisted countries, the ISO code is displayed.

---

## KPI Calculations

### Source of Truth
KPIs are **calculated by the backend** and sent to the frontend in the `/v1/country` response metadata. The frontend displays these values and **caches them** until the next `/v1/country` API call (every 1.5 seconds).

### 1. Gesamt Angriffe (Total Attacks)
**Source**: `metadata.total_attacks` from `/v1/country` endpoint
```
Backend calculation:
= COUNT(ALL unique decision IDs ever received from CrowdSec)

Frontend:
= metadata.total_attacks (cached from last /v1/country response)
```

**Why backend calculates it**:
- Frontend visibleDecisions expire after 10 seconds
- Need persistent count across the app lifetime
- Backend has access to permanent storage/Redis

### 2. Angriffe/Stunde (Attacks Per Hour)
**Source**: `metadata.attacks_per_hour` from `/v1/country` endpoint
```
Backend calculation:
= total_attacks / 24 (average over 24-hour period)

Frontend:
= metadata.attacks_per_hour (cached from last /v1/country response)
```

**Why backend calculates it**:
- More accurate if server has been running for multiple hours
- Prevents inaccurate estimates from short polling windows

### 3. Top Angreifer (Top Attacker)
**Source**: `countries[0]` from `/v1/country` endpoint
```
Frontend display:
= countries[0].countryCode + " (" + countries[0].count + " Angriffe)"

Example: "China (145 Angriffe)"
```

**Why it works**:
- Backend returns countries sorted by count (descending)
- First item is always the top attacker

### 4. Unique Länder (Unique Countries)
**Source**: `metadata.unique_countries` from `/v1/country` endpoint
```
Backend calculation:
= COUNT(DISTINCT country codes in all attacks)

Frontend:
= metadata.unique_countries (cached from last /v1/country response)
```

**Why backend calculates it**:
- More efficient than frontend counting
- Ensures consistency with backend's aggregated data

---

## Error Handling

### API Errors
If the API returns an error status:
```json
{
  "status": "error",
  "message": "Redis client not initialized"
}
```

**Frontend Behavior**:
- Logs error to console with `debugPrint()`
- Returns empty array `[]`
- Dashboard continues to display last known data

### Connection Timeout
- **Timeout**: 5 seconds per request
- **Behavior**: On timeout, request is retried on next polling interval
- **Display**: Dashboard shows "Keine Angriffe registriert" if no data available

---

## Performance Requirements

| Metric | Target | Notes |
|--------|--------|-------|
| Response Time | < 5 seconds | Dashboard timeout setting |
| Data Freshness | < 1.5 seconds | Polling interval |
| Max Decisions | 20 per response | Typical size |
| Max Countries | Unlimited | Frontend takes top 10 |

---

## Request/Response Examples

### Example 1: Normal Decision Response
```bash
$ curl -X GET http://localhost:8000/api/v1/decisions

{
  "status": "success",
  "decision": [
    {
      "decision_2025_01_05_14_30_00": {
        "latitude": 51.5074,
        "longitude": -0.1278,
        "cn": "GB",
        "timestamp": "2025-01-05T14:30:00+01:00"
      }
    }
  ]
}
```

### Example 2: Normal Country Response (with Metadata)
```bash
$ curl -X GET http://localhost:8000/api/v1/country

{
  "status": "success",
  "metadata": {
    "total_attacks": 2847,
    "unique_countries": 47,
    "attacks_per_hour": 119
  },
  "countries": [
    {"CN": 2847},
    {"US": 1234},
    {"RU": 892},
    {"IN": 654},
    {"BR": 456},
    {"JP": 389},
    {"DE": 267},
    {"FR": 198},
    {"GB": 145},
    {"KR": 123}
  ]
}
```

**What the Frontend Dashboard Shows**:
- **Gesamt Angriffe**: 2847 (from `metadata.total_attacks`)
- **Ø pro Stunde**: 119 (from `metadata.attacks_per_hour`)
- **Top Angreifer**: China (2847 Angriffe) (from `countries[0]`)
- **Länder**: 47 (from `metadata.unique_countries`)

---

## Backend Development Notes

### Required Implementation
1. ✅ Stream listener pulls decisions from CrowdSec API
2. ✅ Store decisions in Redis with 20-second TTL
3. ✅ Maintain aggregated country counts in Redis with 24-hour TTL
4. ✅ Add `timestamp` field to each decision (ISO 8601 format)
5. ✅ Return decisions as dictionary with ID as key
6. ✅ Sort countries by count (descending)
7. ✅ **NEW**: Track total attack count (cumulative, never reset)
8. ✅ **NEW**: Calculate metadata in `/v1/country` endpoint:
   - `total_attacks`: Count of all unique decision IDs ever received
   - `unique_countries`: Count of distinct country codes in all attacks
   - `attacks_per_hour`: total_attacks / 24

### Metadata Caching Strategy
- Calculate metadata **once per country fetch**
- Send metadata in `/v1/country` response only
- Frontend caches metadata until next `/v1/country` call
- **Frequency**: Metadata updated ~every 1.5 seconds (polling interval)

### Redis Schema for Tracking
See **Storage Model** above. Keys from the previous design
(`crowdsec:decisions:hash`, `crowdsec:decisions:history`,
`crowdsec:attacks:24h`, `crowdsec:countries:24h`) are no longer written and are
removed by `RedisClient.clear_all()`.

### Optional Enhancements
- Add database persistence for historical data
- Implement WebSocket for real-time updates (instead of polling)
- Add authentication/authorization
- Implement rate limiting
- Add request logging/monitoring
- Implement WebSocket push instead of polling

---

## Testing API

### Test Decisions Endpoint
```bash
# Using curl
curl http://192.168.81.151:30300/api/v1/decisions | jq

# Using Python
import requests
response = requests.get('http://192.168.81.151:30300/api/v1/decisions')
print(response.json())
```

### Test Country Endpoint
```bash
curl http://192.168.81.151:30300/api/v1/country | jq
```

### Validate Country Response Format
```python
# Check if response is valid
response = requests.get('http://localhost:8000/api/v1/country')
data = response.json()

# Validate top-level structure
assert data['status'] == 'success', "Status not success"
assert 'metadata' in data, "Metadata missing"
assert 'countries' in data, "Countries missing"

# Validate metadata
metadata = data['metadata']
assert 'total_attacks' in metadata, "total_attacks missing"
assert 'unique_countries' in metadata, "unique_countries missing"
assert 'attacks_per_hour' in metadata, "attacks_per_hour missing"

assert isinstance(metadata['total_attacks'], int), "total_attacks not int"
assert isinstance(metadata['unique_countries'], int), "unique_countries not int"
assert isinstance(metadata['attacks_per_hour'], int), "attacks_per_hour not int"

# Validate countries array
countries = data['countries']
assert isinstance(countries, list), "Countries not a list"
assert len(countries) > 0, "No countries returned"

# Check first country (should be top attacker)
first_country = countries[0]
country_code = list(first_country.keys())[0]
count = first_country[country_code]
assert isinstance(count, int), "Country count not int"

print("✅ Country response format is valid!")
print(f"Total Attacks: {metadata['total_attacks']}")
print(f"Unique Countries: {metadata['unique_countries']}")
print(f"Attacks/Hour: {metadata['attacks_per_hour']}")
print(f"Top Attacker: {country_code} ({count})")
```

### Validate Decision Response Format
```python
# Check if response is valid
response = requests.get('http://localhost:8000/api/v1/decisions')
data = response.json()

assert data['status'] == 'success', "Status not success"
assert isinstance(data['decision'], list), "Decision not a list"
assert len(data['decision']) > 0, "No decisions returned"

# Check decision structure
decision = data['decision'][0]
decision_id = list(decision.keys())[0]
decision_data = decision[decision_id]

assert 'latitude' in decision_data
assert 'longitude' in decision_data
assert 'cn' in decision_data
assert 'timestamp' in decision_data

print("✅ Decision response format is valid!")
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2025-01-05 | Added metadata to /v1/country endpoint for KPI calculations (total_attacks, unique_countries, attacks_per_hour) |
| 1.0 | 2025-01-05 | Initial API specification with timestamp support |

---

## Support & Issues

For issues or questions about the API:
1. Check the backend logs: `docker logs <backend-container>`
2. Verify Redis connection: `redis-cli ping`
3. Test endpoints manually: `curl -v http://localhost:8000/api/v1/decisions`
4. Review AGENTS.md for development guidelines
