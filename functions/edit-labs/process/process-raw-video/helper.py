import asyncio
from typing import Dict,List,Any
from gemini_helper import gemini_video_understanding_with_youtube_and_schema,gemini_raw_edits_direct_video
from schemas import ReferenceVideoResponseSchema,RawVideoResponseSchema
import constants
import re
import logging
import datetime
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
import json
import aioboto3
from urllib.parse import urlparse
from pathlib import Path
import os
# [FIX] Import Decimal to handle type checking
from decimal import Decimal 

def _format_timedelta(td: datetime.timedelta) -> str:
    """Formats a timedelta object into a zero-padded HH:MM:SS string."""
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

# [FIX] New Helper function to sanitize DynamoDB data
def convert_decimals_to_native(obj):
    """Recursively converts Decimal objects to int or float."""
    if isinstance(obj, list):
        return [convert_decimals_to_native(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_native(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    return obj

async def generate_reference_video_summary(youtube_url:str)->Dict[str,Any]:
    try:
        prompt=constants.REF_VID_SUMMARY_PROMPT
        ref_vid_response=await gemini_video_understanding_with_youtube_and_schema(youtube_url=youtube_url, prompt=prompt,schema=ReferenceVideoResponseSchema)
        print(ref_vid_response)
        print("\n\n\n")
        return ref_vid_response

    except Exception as e:
        raise


async def download_videos_from_s3_async(s3_urls: List[str]) -> List[str]:
    """
    Asynchronously downloads videos from S3 URLs to the /tmp directory.
    """
    download_tasks = []
    session = aioboto3.Session() # Initialize session

    # FIX: Ensure session cleanup is handled gracefully
    try:
        async with session.client("s3") as s3_client:
            for s3_url in s3_urls:
                try:
                    parsed_url = urlparse(s3_url)
                    if parsed_url.scheme != 's3':
                        logger.warning(f"Skipping invalid S3 URL: {s3_url}")
                        continue

                    bucket_name = parsed_url.netloc
                    object_key = parsed_url.path.lstrip('/')
                    
                    file_name = Path(object_key).name 
                    if not file_name: 
                         logger.warning(f"Skipping URL with no filename: {s3_url}")
                         continue

                    local_path = f"/tmp/{file_name}"

                    logger.info(f"Queueing download: s3://{bucket_name}/{object_key} -> {local_path}")
                    
                    task = asyncio.create_task(
                        s3_client.download_file(bucket_name, object_key, local_path),
                        name=local_path 
                    )
                    download_tasks.append(task)

                except Exception as e:
                    logger.error(f"Error parsing or queueing URL {s3_url}: {e}")

            logger.info(f"Starting concurrent download of {len(download_tasks)} files...")
            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            successful_paths = []
            for i, result in enumerate(results):
                task = download_tasks[i]
                local_path = task.get_name() 
                if isinstance(result, Exception):
                    logger.error(f"Failed to download to {local_path}: {result}")
                else:
                    logger.info(f"Successfully downloaded to {local_path}")
                    successful_paths.append(local_path)
    
    finally:
        # FIX: Yield control to the event loop briefly to allow aiohttp to close underlying sockets
        await asyncio.sleep(0.1)

    logger.info(f"Finished downloads. {len(successful_paths)} files successful.")
    return successful_paths





async def generate_edit_instructions_without_ref_ver1(
    s3_urls: list[str],
    channel_info_for_edit: dict,
    creator_notes: str,
    old_file_variables:list,
    existing_file_names: List[str] = []
):
    video_path = [] # Init for cleanup

    try:
        # Format the "No Reference" Prompt
        direct_prompt = constants.RAW_VIDEO_PROMPT_NO_REF.format(
            content_format=channel_info_for_edit.get("content_format",""),
            target_audience=channel_info_for_edit.get("target_audience",""),
            tone_and_vibe=channel_info_for_edit.get("tone_and_vibe",""),
            usp=channel_info_for_edit.get("usp",""),
            primary_topic_of_the_channel=channel_info_for_edit.get("primary_topic_of_the_channel",""),
            creator_notes=creator_notes
        )

        # 1. Always download from S3 (Safety Fallback)
        video_path = await download_videos_from_s3_async(s3_urls=s3_urls)

        # 2. Call Gemini Helper (It will skip upload if existing_file_names are valid)
        response_payload = await gemini_raw_edits_direct_video(
            video_list=video_path,
            schema=RawVideoResponseSchema,
            prompt=direct_prompt,
            existing_file_names=existing_file_names,
            old_file_variables=old_file_variables
        )

        # 3. Unpack Data & Files
        time_stamps = response_payload["data"]
        active_files = response_payload["active_files"]
        files_variables=response_payload["files_variables"]

        # 4. Format Timestamps
        for index, timestamp in enumerate(time_stamps.get("all_edits",{})):
            timestamp["id"] = f"E{index + 1}"
            start_time = timestamp.get("start_time")
            timestamp["start_time"] = _format_timedelta(start_time)
            end_time = timestamp.get("end_time")
            timestamp["end_time"] = _format_timedelta(end_time)
        
        # 5. Return Result + Active Files
        return {
            "data": time_stamps.get("all_edits"),
            "active_files": active_files,
            "files_variables":files_variables
        }

    except Exception as e:
        logger.error(f"Error in No-Ref Ver1 generation: {e}")
        raise
    finally:
        # 6. Cleanup Local Files
        cleanup_local_files(video_path)





async def generate_edit_instructions_without_ref_other_ver(
    s3_urls: list[str],
    channel_info_for_edit: dict,
    creator_notes: str,
    old_edits: Dict[Any,Any],
    old_file_variables:list,
    existing_file_names: List[str] = []
):
    video_path = [] # Init for cleanup

    try:
        # [FIX] Sanitize Decimal objects before serialization
        clean_old_edits = convert_decimals_to_native(old_edits)
        old_edits_str = json.dumps(clean_old_edits, indent=2)

        # Format the "Revision No Reference" Prompt
        direct_prompt = constants.REVISION_VIDEO_PROMPT_NO_REF.format(
            content_format=channel_info_for_edit.get("content_format",""),
            target_audience=channel_info_for_edit.get("target_audience",""),
            tone_and_vibe=channel_info_for_edit.get("tone_and_vibe",""),
            usp=channel_info_for_edit.get("usp",""),
            primary_topic_of_the_channel=channel_info_for_edit.get("primary_topic_of_the_channel",""),
            creator_notes=creator_notes,
            old_edits=old_edits_str # Passed as JSON string
        )

        # 1. Always download
        video_path = await download_videos_from_s3_async(s3_urls=s3_urls)

        # 2. Call Gemini Helper
        response_payload = await gemini_raw_edits_direct_video(
            video_list=video_path,
            schema=RawVideoResponseSchema,
            prompt=direct_prompt,
            existing_file_names=existing_file_names,
            old_file_variables=old_file_variables
        )

        # 3. Unpack
        time_stamps = response_payload["data"]
        active_files = response_payload["active_files"]
        files_variables=response_payload["files_variables"]

        # 4. Format
        for index, timestamp in enumerate(time_stamps.get("all_edits",{})):
            timestamp["id"] = f"E{index + 1}"
            start_time = timestamp.get("start_time")
            timestamp["start_time"] = _format_timedelta(start_time)
            end_time = timestamp.get("end_time")
            timestamp["end_time"] = _format_timedelta(end_time)
        
        # 5. Return
        return {
            "data": time_stamps.get("all_edits"),
            "active_files": active_files,
            "files_variables":files_variables
        }

    except Exception as e:
        logger.error(f"Error in No-Ref Revision generation: {e}")
        raise
    finally:
        # 6. Cleanup Local Files
        cleanup_local_files(video_path)





import json # Ensure this is imported at the top of helper.py

async def generate_edit_instructions_with_ref_ver1(
    reference_youtube_url: str,
    s3_urls: list[str],
    channel_info_for_edit: dict,
    creator_notes: str,
    old_file_variables:list,
    existing_file_names: List[str] = []
):
    # Initialize variable for cleanup in finally block
    video_path = []
    
    try:
        reference_video_edit_summary = await generate_reference_video_summary(youtube_url=reference_youtube_url)
        
        if reference_video_edit_summary == -1:
            logger.info(f"invalid reference video is passed from the user:{reference_youtube_url}")
            return -1
        elif reference_video_edit_summary == -2:
            logger.info(f"The reference video does not exist in the youtube database:{reference_youtube_url}")
            return -2
        else:
            # VERSION 1 PROMPT (Discovery Mode)
            raw_prompt = constants.RAW_VIDEO_PROMPT.format(
                reference_edit_summary=reference_video_edit_summary,
                content_format=channel_info_for_edit.get("content_format", ""),
                target_audience=channel_info_for_edit.get("target_audience", ""),
                tone_and_vibe=channel_info_for_edit.get("tone_and_vibe", ""),
                usp=channel_info_for_edit.get("usp", ""),
                primary_topic_of_the_channel=channel_info_for_edit.get("primary_topic_of_the_channel", ""),
                creator_notes=creator_notes
            )
            
            # 1. Always download to ensure we have fallback if Gemini files expired
            video_path = await download_videos_from_s3_async(s3_urls=s3_urls)
            
            # 2. Call Gemini Helper (Direct Video)
            response_payload = await gemini_raw_edits_direct_video(
                video_list=video_path,
                schema=RawVideoResponseSchema,
                prompt=raw_prompt,
                existing_file_names=existing_file_names,
                old_file_variables=old_file_variables
            )

            # 3. UNPACK response (Data + Files)
            time_stamps = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

            # 4. Process the data (Format timestamps)
            for index, timestamp in enumerate(time_stamps.get("all_edits", {})):
                timestamp["id"] = f"E{index + 1}"
                # Handle start_time
                start_time = timestamp.get("start_time")
                timestamp["start_time"] = _format_timedelta(start_time)
                # Handle end_time
                end_time = timestamp.get("end_time")
                timestamp["end_time"] = _format_timedelta(end_time)

            # 5. Return BOTH data and files
            return {
                "data": time_stamps.get("all_edits"),
                "active_files": active_files,
                "files_variables":files_variables
            }

    except Exception as e:
        logger.error(f"Error in Ver1 generation: {e}")
        raise
    finally:
        # 6. CRITICAL: Clean up local /tmp files
        cleanup_local_files(video_path)


async def generate_edit_instructions_with_ref_other_ver(
    reference_youtube_url: str,
    s3_urls: list[str],
    channel_info_for_edit: dict,
    creator_notes: str,
    old_edits: Dict[Any,Any],
    old_file_variables:list,
    existing_file_names: List[str] = []
):
    video_path = []  # Init for cleanup
    
    try:
        reference_video_edit_summary = await generate_reference_video_summary(youtube_url=reference_youtube_url)
        
        if reference_video_edit_summary == -1:
            logger.info(f"invalid reference video is passed from the user:{reference_youtube_url}")
            return -1
        elif reference_video_edit_summary == -2:
            logger.info(f"The reference video does not exist in the youtube database:{reference_youtube_url}")
            return -2
        else:
            # [FIX] Sanitize Decimal objects before serialization
            clean_old_edits = convert_decimals_to_native(old_edits)
            old_edits_str = json.dumps(clean_old_edits, indent=2)

            # REVISION PROMPT (Correction Mode)
            raw_prompt = constants.REVISION_VIDEO_PROMPT.format(
                reference_edit_summary=reference_video_edit_summary,
                content_format=channel_info_for_edit.get("content_format", ""),
                target_audience=channel_info_for_edit.get("target_audience", ""),
                tone_and_vibe=channel_info_for_edit.get("tone_and_vibe", ""),
                usp=channel_info_for_edit.get("usp", ""),
                primary_topic_of_the_channel=channel_info_for_edit.get("primary_topic_of_the_channel", ""),
                creator_notes=creator_notes,
                old_edits=old_edits_str # Passed as JSON string
            )
            
            # 1. Download (Always, for safety)
            video_path = await download_videos_from_s3_async(s3_urls=s3_urls)
            
            # 2. Generate
            response_payload = await gemini_raw_edits_direct_video(
                video_list=video_path,
                schema=RawVideoResponseSchema,
                prompt=raw_prompt,
                existing_file_names=existing_file_names,
                old_file_variables=old_file_variables
            )

            # 3. Unpack
            time_stamps = response_payload["data"]
            active_files = response_payload["active_files"]
            files_variables=response_payload["files_variables"]

            # 4. Format
            for index, timestamp in enumerate(time_stamps.get("all_edits", {})):
                timestamp["id"] = f"E{index + 1}"
                start_time = timestamp.get("start_time")
                timestamp["start_time"] = _format_timedelta(start_time)
                end_time = timestamp.get("end_time")
                timestamp["end_time"] = _format_timedelta(end_time)

            # 5. Return
            return {
                "data": time_stamps.get("all_edits"),
                "active_files": active_files,
                "files_variables":files_variables
            }

    except Exception as e:
        logger.error(f"Error in Revision generation: {e}")
        raise
    finally:
        cleanup_local_files(video_path)


# Keep your cleanup function as is
def cleanup_local_files(file_paths: list[str]):
    """Removes files from the local /tmp directory."""
    if not file_paths:
        return
    
    logger.info(f"Cleaning up {len(file_paths)} local files...")
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Failed to remove local file {path}: {e}")