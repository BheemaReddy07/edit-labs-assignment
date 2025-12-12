
import json
import logging
import os
import traceback
from decimal import Decimal

# Set up structured logger
logger = logging.getLogger()
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '{"level": "%(levelname)s", "message": "%(message)s", "module": "%(module)s", "function": "%(funcName)s"}'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Environment flag (set this in Lambda env vars)
ENV = os.getenv("ENVIRONMENT", "dev").lower()
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            # Safer to convert to str if precision is critical
            return float(obj)
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)

def get_request_origin(event):
    """Extract the origin from the Lambda event"""
    headers = event.get('headers', {}) or {}
    # API Gateway might have different header casing
    origin = headers.get('Origin') or headers.get('origin')
    return origin

def get_cors_headers(origin=None):
    """Get CORS headers for responses"""
    # Define allowed origins based on environment
    allowed_origins = [
        "http://localhost:5173",
        "https://localhost:5173",
    ]
    
    # Add production domains based on environment
    if ENV == "prod":
        allowed_origins.extend(["https://app.glidee.ai"])
        pass
    
    # Check if the request origin is in our allowed list
    cors_origin = "http://localhost:5173"  # Default to localhost:5173 for development
    if origin and origin in allowed_origins:
        cors_origin = origin
    elif ENV == "prod" and origin:
        # In production, be more restrictive - only allow specific origins
        cors_origin = "null"  # Reject unknown origins in production
    
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": cors_origin,
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Org-Id,X-Requested-With",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Max-Age": "86400"  # Cache preflight for 24 hours
    }

def api_response(status_code, message, data=None, error=None, origin=None):
    """Base response wrapper with CORS headers"""
    response_body = {
        "status": status_code,
        "message": message,
        "data": data,
        "error": error if ENV != "prod" else None
    }

    return {
        "statusCode": status_code,
        "headers": get_cors_headers(origin),
        "body": json.dumps(response_body, cls=DecimalEncoder)
    }

def success_response(data=None, message="Request completed successfully", origin=None):
    logger.info(f"API Success: {message}")
    return api_response(200, message, data=data, origin=origin)

def bad_request_response(user_message="Invalid request", dev_message=None, origin=None):
    logger.warning(f"Bad Request: {user_message} | Details: {dev_message}")
    return api_response(
        400,
        user_message,
        error={
            "type": "BadRequest",
            "details": dev_message
        },
        origin=origin
    )

def not_found_response(user_message="The requested resource was not found", dev_message=None, origin=None):
    logger.warning(f"Not Found: {user_message} | Details: {dev_message}")
    return api_response(
        404,
        user_message,
        error={
            "type": "NotFound",
            "details": dev_message
        },
        origin=origin
    )

def server_error_response(user_message="Oops! Something went wrong.", exception=None, origin=None):
    trace = traceback.format_exc() if exception else "Unknown server error"
    logger.error(f"Server Error: {user_message} | Exception: {trace}")
    return api_response(
        500,
        user_message,
        error={
            "type": "ServerError",
            "details": trace 
        },
        origin=origin
    )

def options_response(origin=None):
    """Handle OPTIONS preflight requests"""
    return {
        "statusCode": 200,
        "headers": get_cors_headers(origin),
        "body": json.dumps({"message": "OK"})
    }
