# Edit Labs App - API Documentation

## Overview

Edit Labs App is a serverless application built on AWS SAM (Serverless Application Model) that manages video projects for creators. It provides APIs to create projects, manage video versions, track editing progress, and submit projects to editors. The application uses API Gateway for HTTP endpoints, Lambda functions for business logic, DynamoDB for data storage, and Step Functions for orchestrating video processing pipelines.

---

## Architecture

### Core Components

- **API Gateway**: RESTful endpoint management with CORS and authentication
- **Lambda Functions**: Serverless compute for business logic
- **DynamoDB**: NoSQL database for project and version storage
- **Step Functions**: Orchestration of video processing workflows
- **S3**: Video storage and management
- **Cognito**: User authentication and authorization

### Technology Stack

- **Runtime**: Python 3.13 (ARM64 architecture)
- **Framework**: AWS SAM (Serverless Application Model)
- **Logging**: AWS Lambda Powertools
- **Database**: Amazon DynamoDB

---

## API Endpoints

### 1. **Create/Submit Project with Video**

**Function**: `CreateProjectFunction`  
**Path**: `POST /editlabs/projects`  
**Handler**: `post-raw-video/app.py`

#### Description
Submits a new video project to the Edit Labs system. Accepts videos from Google Drive links or existing S3 uploads. Automatically triggers the video processing pipeline.

#### Request Body
```json
{
  "channel_id": "string (required)",
  "project_id": "string (required, unique)",
  "title": "string (required)",
  "creator_notes": "string (optional)",
  "reference_video_link": "URL (optional)",
  "drive_link": "URL (optional, Google Drive link)",
  "total_duration": "number (optional, in seconds)"
}
```

#### Response
```json
{
  "status": "success",
  "data": {
    "project_id": "string",
    "execution_name": "string (Step Function execution ID)"
  },
  "message": "Video job successfully submitted and pipeline started."
}
```

#### Features
- **Google Drive Integration**: Downloads video directly from Google Drive if `drive_link` is provided
- **S3 Fallback**: Looks for video files in S3 if no `drive_link` is provided
- **Automatic Pipeline Trigger**: Starts the Step Function pipeline for video processing
- **Duplicate Prevention**: Validates that `project_id` doesn't already exist
- **Duration Tracking**: Automatically extracts or accepts video duration

#### Error Responses
- `400 Bad Request`: Missing required fields, invalid org_id, or duplicate project
- `400 Validation Error`: Video download failed, project already exists
- `500 Server Error`: Unexpected system error

#### Example Usage
```bash
curl -X POST https://{api-endpoint}/editlabs/projects \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "UCxxxxxx",
    "project_id": "proj_001",
    "title": "My Video Project",
    "drive_link": "https://drive.google.com/file/d/xxx/view",
    "creator_notes": "Initial submission"
  }'
```

---

### 2. **List All Projects**

**Function**: `GetProjectsFunction`  
**Path**: `GET /editlabs/projects`  
**Handler**: `getProjects/app.py`

#### Description
Retrieves all projects for the authenticated organization, sorted by creation date (newest first).

#### Request Parameters
None (authenticated by org_id from authorization context)

#### Response
```json
{
  "status": "success",
  "data": [
    {
      "project_id": "string",
      "title": "string",
      "channel_id": "string",
      "created_at": "ISO 8601 timestamp",
      "status": "string (INITIALIZED | PROCESSING | COMPLETED | ERROR)",
      "upload_method": "string (local | drive)",
      "video_count": "number",
      "total_duration": "number (in seconds)",
      "has_reference_video": "boolean",
      "has_creator_notes": "boolean",
      "latest_version_id": "number"
    }
  ],
  "message": "Projects fetched successfully"
}
```

#### Status Values
- `INITIALIZED`: Project created, awaiting processing
- `PROCESSING`: Video is being processed
- `COMPLETED`: Processing finished successfully
- `ERROR`: Processing failed
- `SUBMITED`: Submitted to manual editor

#### Example Usage
```bash
curl -X GET https://{api-endpoint}/editlabs/projects \
  -H "Authorization: Bearer {token}"
```

---

### 3. **Get Project Details with Versions**

**Function**: `GetProjectDetailsFunction`  
**Path**: `GET /editlabs/projects/details`  
**Handler**: `projectDetails/app.py`

#### Description
Retrieves complete details for a specific project including all versions and their metadata.

#### Query Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | The project identifier |

#### Response
```json
{
  "status": "success",
  "data": {
    "org_id": "string",
    "project_id": "string",
    "title": "string",
    "channel_id": "string",
    "created_at": "ISO 8601 timestamp",
    "updated_at": "ISO 8601 timestamp",
    "status": "string",
    "raw_videos_url": ["s3://bucket/path/video.mp4"],
    "reference_video_link": "URL (optional)",
    "creator_notes": "string",
    "requires_manual_editor": "boolean",
    "version_to_edit": "string (optional)",
    "upload_method": "string",
    "total_duration_seconds": "number",
    "versions": [
      {
        "version": "v1 | v2 | ...",
        "status": "INITIALIZED | PROCESSING | COMPLETED | SUBMITED | REJECTED",
        "creator_notes": "string",
        "editor_notes": "string (optional)",
        "created_at": "ISO 8601 timestamp",
        "updated_at": "ISO 8601 timestamp"
      }
    ]
  },
  "message": "Project fetched successfully"
}
```

#### Version Status Values
- `INITIALIZED`: Version created
- `PROCESSING`: Version being processed
- `COMPLETED`: Processing finished
- `SUBMITED`: Awaiting manual editor review
- `REJECTED`: Editor rejected the version

#### Example Usage
```bash
curl -X GET "https://{api-endpoint}/editlabs/projects/details?project_id=proj_001" \
  -H "Authorization: Bearer {token}"
```

---

### 4. **Create New Project Version**

**Function**: `CreateProjectVersionFunction`  
**Path**: `POST /editlabs/projects/create-version`  
**Handler**: `create_version/app.py`

#### Description
Creates a new version of an existing project. Useful for iterative editing and revisions. Automatically triggers the processing pipeline for the new version.

#### Request Body
```json
{
  "project_id": "string (required)",
  "creator_notes": "string (optional)"
}
```

#### Response
```json
{
  "status": "success",
  "data": {
    "project_id": "string",
    "execution_name": "string (Step Function execution ID)"
  },
  "message": "New version created successfully"
}
```

#### Versioning Strategy
- Versions are automatically numbered sequentially (v1, v2, v3, etc.)
- Each version maintains its own processing status
- New versions can reference the previous version's data

#### Error Responses
- `400 Bad Request`: Missing project_id or project not found
- `500 Server Error`: Database or Step Function error

#### Example Usage
```bash
curl -X POST https://{api-endpoint}/editlabs/projects/create-version \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_001",
    "creator_notes": "Revision after feedback"
  }'
```

---

### 5. **Submit Project Version to Editor**

**Function**: `SubmitToEditorFunction`  
**Path**: `POST /editlabs/projects/submit-to-editor`  
**Handler**: `submit_to_editor/app.py`

#### Description
Marks a specific project version as ready for manual editor review. Sets flags in the project to indicate manual editing is required.

#### Request Body
```json
{
  "project_id": "string (required)",
  "version": "string (required, e.g., 'v1', 'v2')",
  "editor_notes": "string (optional)"
}
```

#### Response
```json
{
  "status": "success",
  "data": {
    "project_id": "string",
    "version": "string",
    "status": "SUBMITTED",
    "requires_manual_editor": true
  },
  "message": "Project handed over to manual editor successfully"
}
```

#### Behavior
- Updates the specified version's status to `SUBMITTED`
- Sets `requires_manual_editor` flag to `true` on the main project
- Records `version_to_edit` to indicate which version needs editing
- Stores optional `editor_notes` for context

#### Error Responses
- `400 Bad Request`: Missing fields or version not found
- `500 Server Error`: Database update failed

#### Example Usage
```bash
curl -X POST https://{api-endpoint}/editlabs/projects/submit-to-editor \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_001",
    "version": "v1",
    "editor_notes": "Ready for manual review"
  }'
```

---

### 6. **Submit Feedback** (Feedback Service)

**Function**: `SubmitFeedbackFunction`  
**Path**: `POST /feedback/submit`  
**Handler**: `feedback/app.py`

#### Description
Allows users to submit feedback, bug reports, or feature requests about the platform. Feedback is stored in a dedicated DynamoDB table.

#### Request Body
```json
{
  "message": "string (required)",
  "category": "string (required, e.g., 'bug', 'feature', 'general')",
  "source": "string (optional, e.g., 'web', 'mobile')",
  "rating": "number (optional, 1-5)"
}
```

#### Response
```json
{
  "status": "success",
  "data": {
    "feedback_id": "UUID",
    "created_at": "ISO 8601 timestamp"
  },
  "message": "Feedback submitted successfully"
}
```

#### Feedback Categories
- `bug`: Bug reports
- `feature`: Feature requests
- `general`: General feedback
- `performance`: Performance issues
- `ui/ux`: User interface/experience feedback

#### Features
- Automatic email notification to administrators (via template)
- UUID-based feedback tracking
- User and organization context captured

#### Error Responses
- `400 Bad Request`: Missing required fields
- `500 Server Error`: Database or email service error

#### Example Usage
```bash
curl -X POST https://{api-endpoint}/feedback/submit \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Video processing is too slow",
    "category": "performance",
    "source": "web",
    "rating": 2
  }'
```

---

## Authentication & Authorization

### Cognito Integration
All endpoints (except OPTIONS preflight) require JWT authentication via AWS Cognito.

### Authorization Context
The API extracts the following from the Cognito token:
- `org_id`: Organization identifier (extracted from custom claims)
- `user_id`: User identifier (for feedback tracking)

### Headers Required
```
Authorization: Bearer {cognito_jwt_token}
Content-Type: application/json
```

### CORS Configuration
- **Allowed Origins**: `*` (configurable)
- **Allowed Methods**: `GET, POST, OPTIONS`
- **Allowed Headers**: `Content-Type, Authorization, X-Amz-Date, X-Api-Key, X-Amz-Security-Token`
- **Max Age**: 600 seconds

---

## Data Models

### Project Item (DynamoDB)
```
Partition Key: org_id
Sort Key: project_id

Attributes:
- org_id: String
- project_id: String
- channel_id: String
- title: String
- created_at: ISO 8601 Timestamp
- updated_at: ISO 8601 Timestamp
- status: String
- upload_method: String (local | drive)
- total_duration_seconds: Number
- requires_manual_editor: Boolean
- version_to_edit: String (optional)
- raw_videos_url: List[String] (S3 URIs)
- reference_video_link: String (optional)
- creator_notes: String (optional)
- versions: List[VersionObject]
```

### Version Object
```
{
  "version": "v1",
  "status": "INITIALIZED | PROCESSING | COMPLETED | SUBMITED | REJECTED",
  "creator_notes": "String",
  "editor_notes": "String (optional)",
  "created_at": "ISO 8601 Timestamp",
  "updated_at": "ISO 8601 Timestamp"
}
```

### Feedback Item (DynamoDB)
```
Partition Key: feedback_id
Sort Key: None

Attributes:
- feedback_id: UUID
- user_id: String
- primary_org_id: String
- createdAt: ISO 8601 Timestamp
- message: String
- category: String
- source: String (optional)
- rating: Number (optional, 1-5)
```

---

## Deployment

### Prerequisites
- AWS SAM CLI installed
- AWS credentials configured
- Python 3.13 runtime available
- DynamoDB table created
- S3 bucket configured
- Cognito User Pool set up
- Step Function state machine deployed

### Environment Configuration

#### SSM Parameters Required
```
/prod/tables/edit-labs                  # DynamoDB table name
/prod/auth/cognito_userpool_arn         # Cognito User Pool ARN
/prod/auth/authorizer_alias_arn         # Lambda authorizer ARN
/prod/sfn/edit-labs-pipeline-arn        # Step Function ARN
/prod/s3/edit-labs                      # S3 bucket name (created automatically)
```

### Build & Deploy
```bash
# Build the SAM application
sam build

# Deploy to AWS
sam deploy --guided

# For subsequent deployments
sam deploy
```

### Configuration Files
- `samconfig.toml`: SAM deployment configuration
- `template.yaml`: CloudFormation/SAM template defining all resources

---

## Error Handling

### Standard Error Responses

#### 400 Bad Request
```json
{
  "status": "error",
  "message": "Descriptive error message",
  "origin": "request-origin"
}
```

#### 500 Server Error
```json
{
  "status": "error",
  "message": "An unexpected error occurred",
  "origin": "request-origin"
}
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `org_id missing` | No authorization token or invalid claims | Ensure valid JWT token in Authorization header |
| `Missing request body` | Empty POST request | Include JSON body in request |
| `Project not found` | Invalid project_id for organization | Verify project_id exists for your org |
| `Version not found` | Invalid version string (e.g., 'v99') | Use valid version identifier |
| `Project already exists` | Duplicate project_id submission | Use unique project_id |
| `Failed to download from drive_link` | Invalid Google Drive link or permission issue | Verify Drive link is public and valid |

---

## Shared Utilities

### SharedUtilsLayer
Provides common utilities across all Lambda functions:

**Location**: `layers/shared_utils/`

**Modules**:
- `common_response_utils.py`: Standardized response formatting and CORS handling
- `dynamodb_helper.py`: DynamoDB operations wrapper
- `exceptions.py`: Custom exception definitions

**Key Classes**:
- `DynamoDBHelper`: Simplified DynamoDB CRUD operations
- `ValidationError`: Custom validation exception

**Key Functions**:
- `success_response()`: Format successful API responses
- `bad_request_response()`: Format 400 error responses
- `server_error_response()`: Format 500 error responses
- `options_response()`: Format CORS preflight responses
- `get_request_origin()`: Extract CORS origin from request

---

## Logging & Monitoring

### AWS Lambda Powertools Integration
All functions use AWS Lambda Powertools for structured logging:

```python
from aws_lambda_powertools import Logger, Tracer

logger = Logger(service="function-name")
tracer = Tracer(service="function-name")

@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context):
    logger.info("Processing request")
    logger.exception("Error occurred")
```

### Log Configuration
- **Service Name**: Function-specific (e.g., "edit-labs-create-project")
- **Metrics Namespace**: "EditLabs"
- **Log Level**: INFO (configurable)
- **Auto-instrumentation**: Request/response logging

### CloudWatch Logs
All function logs are available in CloudWatch under:
```
/aws/lambda/{FunctionName}
```

---

## Performance & Limits

### Function Configuration

| Function | Memory | Timeout | Purpose |
|----------|--------|---------|---------|
| CreateProjectFunction | 512 MB | 300s | Video upload, GDrive download |
| GetProjectsFunction | 512 MB | 30s | List projects |
| GetProjectDetailsFunction | 512 MB | 30s | Fetch project details |
| CreateProjectVersionFunction | 512 MB | 30s | Create new version |
| SubmitToEditorFunction | 512 MB | 30s | Submit to editor |
| SubmitFeedbackFunction | 512 MB | 30s | Process feedback |

### Scalability
- **API Gateway**: Auto-scales to handle concurrent requests
- **Lambda**: Auto-provisioned concurrency as needed
- **DynamoDB**: On-demand billing (auto-scales read/write capacity)

---

## Troubleshooting

### Video Upload Issues
1. **Google Drive download fails**:
   - Verify the drive_link is publicly accessible
   - Ensure the file is a valid video format
   - Check S3 bucket permissions

2. **S3 fallback doesn't find video**:
   - Verify video exists in `{org_id}/{channel_id}/{project_id}/v1/raw-video/` prefix
   - Check S3 bucket name matches configuration

### Processing Pipeline Issues
1. **Step Function not starting**:
   - Verify Step Function ARN in SSM parameters
   - Check Lambda has `states:StartExecution` permission
   - Review Step Function execution logs

2. **Version creation fails**:
   - Verify project_id exists
   - Check DynamoDB has write capacity
   - Ensure versions array isn't corrupted

### Authentication Issues
1. **Access Denied org_id missing**:
   - Verify JWT token contains org_id claim
   - Check Cognito user pool configuration
   - Validate Lambda authorizer implementation

---

## Related Services

### Step Function Pipeline
Video processing orchestration:
- Location: `edit-labs-pipeline/` folder
- State Machine: `statemachine.asl.json`
- Processes raw videos and generates outputs

### Video Processing (ECS)
Located in `process/process-raw-video/`:
- Docker-based video processing
- Terraform infrastructure as code
- Integrates with Gemini AI for content analysis

---

## Future Enhancements

- [ ] Webhook support for pipeline completion notifications
- [ ] Batch project operations
- [ ] Advanced filtering and search on project list
- [ ] Version comparison API
- [ ] Automated quality checks before editor submission
- [ ] Project sharing and collaboration
- [ ] Project archival and restoration
- [ ] Advanced analytics dashboard

---

## Support & Contact

For issues, questions, or feature requests:
1. Submit feedback via the feedback API
2. Check CloudWatch logs for error details
3. Review deployment configuration in `samconfig.toml`
4. Contact the development team with CloudWatch execution ID

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Nov 2024 | Initial API documentation |
| 1.1 | Current | Added Google Drive integration, Feedback API |

---

## License & Security

- **Authentication**: AWS Cognito with JWT tokens
- **Encryption**: TLS 1.2+ for data in transit
- **Data Protection**: DynamoDB encryption at rest
- **Network**: Private Lambda functions, managed by API Gateway
- **CORS**: Configurable origin restrictions

---

**Last Updated**: November 2024  
**API Version**: 1.0  
**Status**: Production Ready
