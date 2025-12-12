import boto3
import logging
import time
import random
from typing import Dict, Optional, Any
from botocore.exceptions import ClientError
from decimal import Decimal
from exceptions import DynamoDBError, ValidationError

logger = logging.getLogger(__name__)

class DynamoDBHelper:
    """A streamlined DynamoDB helper for basic CRUD operations."""

    def __init__(self, table_name: str, region: str = None):
        if not table_name:
            raise ValidationError("Table name cannot be empty")

        self.table_name = table_name
        self.region = region or 'us-east-1'
        self.max_retries = 3
        self.base_delay = 1.0
        
        try:
            self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
            self.table = self.dynamodb.Table(table_name)
        except Exception as e:
            raise DynamoDBError(f"Failed to initialize DynamoDB helper: {e}")
    
    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = self.base_delay * (2 ** attempt)
        return delay + random.uniform(0.1, 0.3) * delay
    
    def _should_retry(self, error: ClientError, attempt: int) -> bool:
        """Determine if an error should be retried."""
        if attempt >= self.max_retries:
            return False
        
        retriable_errors = ['ProvisionedThroughputExceededException', 'ThrottlingException']
        return error.response['Error']['Code'] in retriable_errors
    
    def _sanitize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize item data for DynamoDB with proper type conversion."""
        # Converts floats to Decimals and handles empty strings
        def clean_value(value):
            if isinstance(value, float):
                return Decimal(str(value))
            if value == '':
                return None
            return value
        
        return {k: clean_value(v) for k, v in item.items() if v is not None}

    def put_item(self, item: Dict[str, Any]) -> bool:
        """Put an item with proper sanitization and retry logic."""
        if not item:
            raise ValidationError("Item cannot be empty")
        
        sanitized_item = self._sanitize_item(item)
        for attempt in range(self.max_retries + 1):
            try:
                self.table.put_item(Item=sanitized_item)
                return True
            except ClientError as e:
                if self._should_retry(e, attempt):
                    time.sleep(self._calculate_backoff_delay(attempt))
                    continue
                logger.error(f"DynamoDB put_item failed: {e.response['Error']}")
                raise DynamoDBError(f"Could not save item: {e}")
        return False
    
    def get_item(self, key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get an item from the table with retry logic."""
        if not key:
            raise ValidationError("Key cannot be empty")
        
        for attempt in range(self.max_retries + 1):
            try:
                response = self.table.get_item(Key=key)
                return response.get('Item')
            except ClientError as e:
                if self._should_retry(e, attempt):
                    time.sleep(self._calculate_backoff_delay(attempt))
                    continue
                logger.error(f"DynamoDB get_item failed: {e.response['Error']}")
                raise DynamoDBError(f"Could not retrieve item: {e}")
        return None
