FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy only requirements first for better layer caching
COPY pyproject.toml ./

# Install Python dependencies (includes streamlit)
RUN pip install --no-cache-dir -e .

# Copy the application code
COPY backend/ ./backend/
COPY ui/ ./ui/
COPY docs/ ./docs/

# Expose Streamlit default port
EXPOSE 8501

# Set environment variable for backend URL (can be overridden in docker-compose)
ENV BACKEND_URL=http://backend:8000

# Run Streamlit app
CMD ["streamlit", "run", "ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
