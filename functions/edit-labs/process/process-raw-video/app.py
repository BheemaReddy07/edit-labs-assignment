import os
import json
import sys
import boto3
from datetime import datetime, timezone
import asyncio
from decimal import Decimal
from typing import Any, Dict

from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

import constants
from helper import generate_edit_instructions_with_ref_other_ver, generate_edit_instructions_with_ref_ver1, generate_edit_instructions_without_ref_ver1, generate_edit_instructions_without_ref_other_ver
# NEW IMPORT
from gemini_helper import cleanup_gemini_files 

logger = Logger(service=f"{constants.SERVICE_NAME}-pipeline-step")

dynamodb = boto3.resource('dynamodb')

PAYLOAD_JSON = os.environ.get('PAYLOAD_JSON')

RECC_TABLE_NAME = constants.RECC_DYNAMODB_TABLE
EDITLABS_TABLE_NAME = constants.EDITTABLE_TABLE

def floats_to_decimals(obj: Any) -> Any:
    if isinstance(obj, list):
        return [floats_to_decimals(i) for i in obj]
    if isinstance(obj, dict):
        return {k: floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _parse_payload(event):
    body = event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body
    return {}

async def main():
    org_id = None
    project_id = None
    version_index = None # Initialize for safety

    try:
        if not PAYLOAD_JSON or not EDITLABS_TABLE_NAME or not RECC_TABLE_NAME:
            raise ValueError("Missing required environment variables")

        payload = _parse_payload(PAYLOAD_JSON)
        org_id = payload.get("org_id")
        project_id = payload.get("project_id")
        clean_request = payload.get("clean",0) # <--- CHECK FOR CLEAN FLAG

        if not org_id or not project_id:
             raise ValueError("Missing 'org_id' or 'project_id' in PAYLOAD_JSON")

        # Initialize Table
        editlabs_table = dynamodb.Table(EDITLABS_TABLE_NAME)

        # ==============================================================================
        # BRANCH: CLEANUP REQUEST (User Accepted Edits)
        # ==============================================================================
        if clean_request:
            logger.info("=" * 60)
            logger.info("🧹 CLEANUP REQUEST RECEIVED")
            logger.info("=" * 60)
            logger.info(f"Org: {org_id}, Project: {project_id}")

            # 1. Fetch the project to find file names
            logger.info("Fetching project to retrieve active Gemini files...")
            edit_job_response = await asyncio.to_thread(
                editlabs_table.get_item,
                Key={'org_id': org_id, 'project_id': project_id}
            )
            edit_item = edit_job_response.get("Item")
            
            if not edit_item:
                logger.warning(f"Project {project_id} not found. Skipping cleanup.")
                return

            # 2. Get the file list from DynamoDB
            files_to_delete = edit_item.get("existing_file_names", [])
            
            if files_to_delete:
                # 3. Call the Gemini Cleanup Function
                await cleanup_gemini_files(files_to_delete)
            else:
                logger.info("No 'existing_file_names' found in DynamoDB. Nothing to clean on Gemini.")

            # 4. Remove the file references from DynamoDB (so we don't try to use them again)
            logger.info("Removing 'existing_file_names' from DynamoDB record...")
            await asyncio.to_thread(
                editlabs_table.update_item,
                Key={'org_id': org_id, 'project_id': project_id},
                UpdateExpression="REMOVE existing_file_names"
            )
            
            logger.info("✅ Cleanup sequence finished successfully.")
            # EXIT: Do not proceed to generation logic
            return 

        # ==============================================================================
        # STANDARD FLOW: EDIT GENERATION
        # ==============================================================================
        version = payload.get("version")
        if not version:
             raise ValueError("Missing 'version' in PAYLOAD_JSON (and 'clean' was not requested)")

        logger.info("=" * 60)
        logger.info("🚀 STARTING EDIT GENERATION PIPELINE STEP")
        logger.info("=" * 60)
        logger.info(f"Project ID (Job ID): {project_id}")
        logger.info(f"Org ID: {org_id}")
        logger.info("=" * 60)

        recc_table = dynamodb.Table(RECC_TABLE_NAME)

        logger.info("Fetching edit job details.")
        edit_job_response = await asyncio.to_thread(
            editlabs_table.get_item,
            Key={'org_id': org_id, 'project_id': project_id}
        )
        edit_item = edit_job_response.get("Item")
        versions_list = edit_item.get("versions", [])
        
        # Calculate Index Early for Error Handling
        version_index = next(
            (i for i, item in enumerate(versions_list) if item.get("version") == version), 
            None
        )
        if version_index is None:
            raise ValueError(f"Version '{version}' not found in project '{project_id}'")

        # ... (Rest of your existing generation logic goes here) ...
        
        channel_id = edit_item.get("channel_id")
        raw_video_urls = edit_item.get("raw_videos_url")
        reference_url = edit_item.get("reference_video_link")
        existing_file_names = edit_item.get("existing_file_names", [])
        old_files_variables=edit_item.get("files_variables",[])
        
        target_version_data = next(
            (item for item in versions_list if item.get("version") == version), 
            None
        )
        logger.info(f"Found data for version: {target_version_data.get('version')}")

        creator_notes = target_version_data.get("creator_notes")
        
        # Get old edits if this is a revision
        old_edits = {}
        if version != "v1":
            old_version = f"v{str(int(version[1:])-1)}"
            old_version_data = next(
                (item for item in versions_list if item.get("version") == old_version), 
                None
            )
            if not old_version_data:
                raise ValueError(f"Could not find previous version data ({old_version}) required for revision.")
            old_edits = old_version_data.get("all_edits", {})

        if not channel_id: raise ValueError(f"Job {project_id} is missing 'channel_id'.")
        if not creator_notes: raise ValueError(f"Job {project_id} is missing 'creator_notes'.")
        if not raw_video_urls: raise ValueError(f"Job {project_id} is missing 'raw_video_urls'.")

        # ... (Context Fetching Logic) ...
        logger.info(f"Fetching context data for channel_id={channel_id}")
        partition_key = org_id
        sort_key_prefix = f"CHANNEL_CONTEXT#{channel_id}#"
        context_response = await asyncio.to_thread(
            recc_table.query,
            KeyConditionExpression=Key('org_id').eq(partition_key) & Key('id').begins_with(sort_key_prefix),
            Limit=1,
            ScanIndexForward=False
        )
        context_items = context_response.get("Items", [])
        if not context_items:
            raise ValueError(f"No context data found for org_id={org_id} and channel_id={channel_id}")
        context_item = context_items[0]
        channel_info = context_item.get("channel_info_for_thumbnails", {})
        if not channel_info:
            raise ValueError("Channel info data is empty or missing from context item.")

        # Mark Status as STARTED
        time_now_started = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            editlabs_table.update_item,
            Key={'org_id': org_id, 'project_id': project_id},
            UpdateExpression=f"SET #versions[{version_index}].#status = :status, #versions[{version_index}].#updated_at = :updated_at,#out_updated_at = :out_updated_at",
            ExpressionAttributeNames={
                '#versions': 'versions',      
                '#status': 'status',          
                '#updated_at': 'updated_at',
                '#out_updated_at': 'updated_at'
            },
            ExpressionAttributeValues={
                ':status': 'STARTED',
                ':updated_at': time_now_started,
                ':out_updated_at':time_now_started
            }
        )

        final_json = None
        edits = None
        active_files = []

        if reference_url and version == 'v1':
            logger.info("Generating edit instructions with reference video.")
            response_payload = await generate_edit_instructions_with_ref_ver1(
                reference_youtube_url=reference_url,
                s3_urls=raw_video_urls,
                channel_info_for_edit=channel_info,
                creator_notes=creator_notes,
                existing_file_names=existing_file_names,
                old_file_variables=old_files_variables
            )
            if response_payload == -1: raise ValueError("Invalid reference URL passed")
            if response_payload == -2: raise ValueError("Reference video does not exist")
            edits = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

        elif reference_url and version != 'v1':
            logger.info("Generating edit instructions with reference video (other version).")
            response_payload = await generate_edit_instructions_with_ref_other_ver(
                reference_youtube_url=reference_url,
                s3_urls=raw_video_urls,
                channel_info_for_edit=channel_info,
                creator_notes=creator_notes,
                existing_file_names=existing_file_names,
                old_edits=old_edits,
                old_file_variables=old_files_variables
            )
            if response_payload == -1: raise ValueError("Invalid reference URL passed")
            if response_payload == -2: raise ValueError("Reference video does not exist")
            edits = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

        elif reference_url is None and version == "v1":
            logger.info("Generating edit instructions without reference video.")
            response_payload = await generate_edit_instructions_without_ref_ver1(
                s3_urls=raw_video_urls,
                channel_info_for_edit=channel_info,
                creator_notes=creator_notes,
                existing_file_names=existing_file_names,
                old_file_variables=old_files_variables
            )
            edits = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

        else:
            response_payload = await generate_edit_instructions_without_ref_other_ver(
                s3_urls=raw_video_urls,
                channel_info_for_edit=channel_info,
                creator_notes=creator_notes,
                existing_file_names=existing_file_names,
                old_edits=old_edits,
                old_file_variables=old_files_variables
            )
            edits = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

        if not edits:
            raise ValueError("Edit generation process returned no result.")

        logger.info("Edit generation successful.")
        time_now_done = datetime.now(timezone.utc).isoformat()
        
        # Update DynamoDB with Success
        await asyncio.to_thread(
            editlabs_table.update_item,
            Key={'org_id': org_id, 'project_id': project_id},
            UpdateExpression=f"""SET 
                #versions[{version_index}].#status = :status, 
                #versions[{version_index}].#updated_at = :updated_at,
                #versions[{version_index}].#all_edits = :all_edits,
                #existing_file_names = :existing_file_names,
                #files_variables = :files_variables,
                #out_updated_at = :out_updated_at

            """,
            ExpressionAttributeNames={
                '#versions': 'versions',
                '#status': 'status',
                '#updated_at': 'updated_at',
                '#all_edits': 'all_edits',       
                '#existing_file_names': 'existing_file_names',
                '#files_variables' : 'files_variables',
                '#out_updated_at': 'updated_at'
            },
            ExpressionAttributeValues={
                ':status': 'DONE',
                ':updated_at': time_now_done,
                ':all_edits': floats_to_decimals(edits), 
                ':existing_file_names': active_files,
                ':files_variables' : files_variables,
                ':out_updated_at':time_now_done
            }
        )

        logger.info("Edit Generation Step completed successfully!")
        await asyncio.sleep(0.25)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        
        # Only attempt status update if this was a GENERATION attempt (we have an index)
        # If it was a clean attempt, we just raise
        if org_id and project_id and version_index is not None and 'editlabs_table' in locals():
            try:
                logger.info("Attempting to update status to FAILED in DynamoDB...")
                time_now_failed = datetime.now(timezone.utc).isoformat()
                
                await asyncio.to_thread(
                    editlabs_table.update_item,
                    Key={'org_id': org_id, 'project_id': project_id},
                    UpdateExpression=f"SET #versions[{version_index}].#status = :status, #versions[{version_index}].#updated_at = :updated_at,#out_updated_at = :out_updated_at",
                    ExpressionAttributeNames={
                        '#versions': 'versions',
                        '#status': 'status',
                        '#updated_at': 'updated_at',
                        '#out_updated_at': 'updated_at'
                    },
                    ExpressionAttributeValues={
                        ':status': 'FAILED',
                        ':updated_at': time_now_failed,
                        ':out_updated_at':time_now_failed
                    }
                )
            except Exception as update_err:
                logger.error(f"CRITICAL: Failed to update DynamoDB status to FAILED: {update_err}")

        raise e

if __name__ == '__main__':
    asyncio.run(main())
