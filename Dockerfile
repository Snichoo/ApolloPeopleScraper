# Use the official Playwright Python image
FROM mcr.microsoft.com/playwright/python:v1.38.0-focal

# Set environment variables to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Set the working directory
WORKDIR /app

# Copy the application code into the container
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (this ensures all required browsers are installed)
RUN playwright install --with-deps

# Set environment variables for Flask and Google Cloud Run
ENV PORT 8080
ENV PYTHONUNBUFFERED True

# Expose the port for Google Cloud Run
EXPOSE 8080

# Command to run your application
CMD ["python", "main.py"]
