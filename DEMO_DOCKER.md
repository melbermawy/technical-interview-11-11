# Docker Demo - Travel Planner

This document provides instructions for running the Travel Planner system using Docker Compose.

## Prerequisites

- Docker Engine 20.10+ and Docker Compose v2.0+
- (Optional) OpenAI API key for real LLM-powered planning

## Quick Start

### 1. Environment Setup

Create a `.env` file in the project root (or set environment variables):

```bash
# Optional: Set OpenAI API key for real LLM behavior
# If unset, the system will run with stub/fixture data
OPENAI_API_KEY=sk-...

# Optional: Set weather API key
WEATHER_API_KEY=your_openweathermap_key
```

### 2. Build and Start Services

```bash
docker compose up --build
```

This will:
- Start PostgreSQL on port 5432
- Run database migrations automatically
- Start the FastAPI backend on port 8000
- Start the Streamlit UI on port 8501

### 3. Access the Application

Open your browser to:
- **UI**: http://localhost:8501
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### 4. Stop Services

```bash
docker compose down
```

To also remove the database volume:

```bash
docker compose down -v
```

## Service Details

### PostgreSQL Database
- **Container**: `travel_planner_postgres`
- **Image**: `postgres:15-alpine`
- **Port**: 5432
- **Database**: `travel_planner`
- **User**: `travel_user`
- **Password**: `travel_pass`
- **Volume**: `postgres_data` (persists data across restarts)

### Backend API
- **Container**: `travel_planner_backend`
- **Port**: 8000
- **Healthcheck**: `GET /health`
- **Startup**: Runs `alembic upgrade head` before starting server
- **Dependencies**: Waits for postgres healthcheck to pass

### Streamlit UI
- **Container**: `travel_planner_ui`
- **Port**: 8501
- **Backend URL**: `http://backend:8000` (internal docker network)
- **Dependencies**: Waits for backend healthcheck to pass

## Database Migrations

Migrations run automatically when the backend container starts. To manually run migrations:

```bash
# Exec into backend container
docker compose exec backend bash

# Run migrations
alembic upgrade head
```

To create a new migration:

```bash
docker compose exec backend bash
alembic revision -m "description"
```

## Development Workflow

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f ui
docker compose logs -f postgres
```

### Rebuilding After Code Changes

```bash
# Rebuild and restart specific service
docker compose up --build backend

# Rebuild all services
docker compose up --build
```

### Connecting to PostgreSQL

```bash
# Using docker compose
docker compose exec postgres psql -U travel_user -d travel_planner

# Using local psql client
psql postgresql://travel_user:travel_pass@localhost:5432/travel_planner
```

## LLM Behavior

### With OpenAI API Key
If `OPENAI_API_KEY` is set in the environment, the system will:
- Use real LLM calls for planning and synthesis
- Generate dynamic responses based on user input
- Incur API costs

### Without OpenAI API Key (Stub Mode)
If `OPENAI_API_KEY` is unset or empty, the system will:
- Use fixture/stub data for responses
- Return predefined plans and itineraries
- Work offline with no API costs

## Troubleshooting

### Backend fails to start
Check if postgres is healthy:
```bash
docker compose ps
docker compose logs postgres
```

### Migrations fail
Ensure DATABASE_URL is correctly configured:
```bash
docker compose exec backend env | grep DATABASE_URL
```

### UI can't connect to backend
Verify backend healthcheck is passing:
```bash
curl http://localhost:8000/health
```

### Port conflicts
If ports 5432, 8000, or 8501 are already in use, update `docker-compose.yml` port mappings.

## Production Considerations

This Docker setup is suitable for **local development and demos**. For production:

1. **Security**:
   - Use secrets management for DATABASE_URL, API keys
   - Don't commit `.env` with real credentials
   - Configure JWT keys properly (not placeholders)

2. **Performance**:
   - Use a managed PostgreSQL service (not local container)
   - Configure connection pooling
   - Add Redis for caching (currently stubbed)

3. **Observability**:
   - Add structured logging
   - Configure health check endpoints
   - Monitor postgres connection pool

4. **Reliability**:
   - Set restart policies on containers
   - Configure resource limits
   - Use persistent volumes for postgres data

## Next Steps

- Read the main [README.md](./README.md) for project architecture
- Review API documentation at http://localhost:8000/docs
- Check database schema in `backend/app/db/models.py`
- Explore migrations in `backend/app/db/alembic/versions/`
