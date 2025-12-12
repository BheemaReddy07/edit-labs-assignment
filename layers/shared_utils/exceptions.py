"""Custom exception classes for the Edit Labs service."""
  
class ValidationError(Exception):
    """Raised when input validation fails."""
    pass

class DynamoDBError(Exception):
    """Raised when DynamoDB operations fail."""
    pass
