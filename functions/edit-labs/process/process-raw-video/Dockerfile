# Use ARM64-compatible Python base image
FROM python:3.13-slim
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Or list them explicitly if you prefer more control
COPY app.py helper.py gemini_helper.py schemas.py constants.py ./

# Run the main application script
CMD ["python", "app.py"]