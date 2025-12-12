import logging
from typing import List,Type,Dict,Any
import time
import httpx
from pydantic import BaseModel,Field,ValidationError
import json
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
import asyncio
import os
import re
from googleapiclient.discovery import build
from datetime import timedelta
import constants

from google import genai
from google.genai import types
from google.api_core import exceptions as core_exceptions
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build

youtube_api=constants.YOUTUBE_API_KEY


def _get_video_id(url: str) -> str | None:
    """Extracts the YouTube video ID."""
    if not isinstance(url, str):
        return None
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([\w-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None


def _parse_iso8601_duration(duration_string: str) -> int:
    """Converts an ISO 8601 duration string to total seconds."""
    try:
        if duration_string.startswith('PT'):
            duration_string = duration_string[2:]
        total_seconds = 0
        hours = 0
        minutes = 0
        seconds = 0
        if 'H' in duration_string:
            hours_part, duration_string = duration_string.split('H')
            hours = int(hours_part)
        if 'M' in duration_string:
            minutes_part, duration_string = duration_string.split('M')
            minutes = int(minutes_part)
        if 'S' in duration_string:
            seconds_part = duration_string.replace('S', '')
            seconds = int(seconds_part)
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds
    except Exception as e:
        raise


async def youtube_video_exists(url: str,video_id:str) -> int|bool:
    """Checks if a YouTube video exists using the YouTube Data API v3."""
    if not video_id:
        return False
    api_key = youtube_api
    if not api_key:
        logger.error("YOUTUBE_API_KEY environment variable not set.")
        return False
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        request = youtube.videos().list(part="id", id=video_id)
        response = await asyncio.to_thread(request.execute)
        if response.get('items'):
            return True
        else:
            return False
    except HttpError as e:
        logger.error(f"An HTTP error {e.resp.status} occurred: {e.content}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during API validation: {e}")
        return False


async def _get_youtube_video_duration(video_id: str) -> int | None:
    """Fetches video duration from the YouTube Data API."""
    try:
        youtube = build('youtube', 'v3', developerKey=youtube_api)
        request = youtube.videos().list(part="contentDetails", id=video_id)
        response = await asyncio.to_thread(request.execute)
        if not response.get("items"):
            logger.error(f"Error: Video with ID '{video_id}' not found.")
            raise
        iso_duration = response['items'][0]['contentDetails']['duration']
        return _parse_iso8601_duration(iso_duration)
    except Exception as e:
        print(f"An API error occurred: {e}")
        raise 

# --- NEW HELPER FUNCTION TO WAIT FOR PROCESSING ---
async def _wait_for_files_active(client, files: List[Any]):
    """
    Waits for uploaded Gemini files to transition from PROCESSING to ACTIVE state.
    """
    logger.info("Waiting for file processing to complete...")
    for name in files:
        # Support both raw objects and string names
        file_id = name.name if hasattr(name, 'name') else name
        
        # Safety timeout loop (max 60s per file)
        for _ in range(12):
            try:
                # Poll file status
                file = await client.files.get(name=file_id)
                if file.state.name == "ACTIVE":
                    logger.info(f"File {file_id} is ACTIVE and ready.")
                    break
                elif file.state.name == "FAILED":
                    raise RuntimeError(f"File {file_id} failed to process.")
                
                logger.info(f"File {file_id} is {file.state.name}. Waiting 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.warning(f"Error checking file status for {file_id}: {e}")
                await asyncio.sleep(2)

async def gemini_video_understanding_with_youtube_and_schema(youtube_url:str,schema:Type[BaseModel],prompt:str)->Dict[Any,Any]|str|int:
    """
    Analyzes a YouTube video using the Gemini model.
    """
    client = None
    async_client = None
    
    try:
        client = genai.Client(api_key=constants.GEMINI_API_KEY)
        async_client = client.aio
        
        async def _count_tokens(url: str) -> int:
            try:
                token_count_response = await async_client.models.count_tokens(
                    model='gemini-2.5-flash',
                    contents=types.Content(parts=[types.Part(file_data=types.FileData(file_uri=url))]),
                )
                return token_count_response.total_tokens
            except core_exceptions.InvalidArgument:
                logger.info("Video size exceeds token counting limits, proceeding with chunking.")
                return -1
            except Exception as e:
                logger.error(f"An unexpected error occurred during token counting: {e}")
                return -1

        video_id=_get_video_id(url=youtube_url)

        if not video_id:
            logger.error("user has passed an invalid url as video id does not exists.")
            return -1

        exists= await youtube_video_exists(url=youtube_url,video_id=video_id)
        if not exists:
            logger.error("The passed video does not exist in youtube.")
            return -2

        token_count = await _count_tokens(youtube_url)
        if token_count != -1 and token_count < 1500000:
            logger.info("Video is small enough to be processed in a single call.")
            MAX_RETRIES = 3
            delay = 3
            for attempt in range(MAX_RETRIES):
                try:
                    logger.info(f"Attempt number: {attempt + 1}")
                    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.4)
                    response = await async_client.models.generate_content(
                        model='gemini-2.5-pro',
                        contents=types.Content(
                            parts=[
                                types.Part(file_data=types.FileData(file_uri=youtube_url)),
                                types.Part(text=prompt)
                            ]
                        ),
                        config=config
                    )
                    return schema.model_validate_json(response.text).model_dump().get("explanation","")
                except (ValidationError, json.JSONDecodeError) as e:
                    logger.warning(f"Attempt {attempt + 1} failed validation. Error: {e}")
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1} failed with error: {e}")

                if attempt < MAX_RETRIES - 1:
                    logger.info(f"Waiting {delay} seconds before next retry...")
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error("Exceeded the maximum limit of retries for single-call processing.")
                    raise
        else:
            logger.info("Video is large, processing in concurrent chunks.")
            video_id = _get_video_id(youtube_url)
            if not video_id:
                raise ValueError("Could not extract video ID from the YouTube URL.")
            duration = await _get_youtube_video_duration(video_id=video_id)
            config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.4)
            chunk_duration_seconds = 1800  # 30 minutes

            async def _process_chunk_with_retry(start_time: int, end_time: int) -> str:
                MAX_RETRIES_CHUNK = 3
                delay_chunk = 3
                start_offset_str = f"{start_time}s"
                end_offset_str = f"{end_time}s"

                for attempt in range(MAX_RETRIES_CHUNK):
                    try:
                        logger.info(f"Processing chunk {start_offset_str}-{end_offset_str}, attempt {attempt + 1}")
                        response = await async_client.models.generate_content(
                            model='gemini-2.5-pro',
                            contents=types.Content(
                                parts=[
                                    types.Part(
                                        file_data=types.FileData(file_uri=youtube_url),
                                        video_metadata=types.VideoMetadata(
                                            start_offset=start_offset_str,
                                            end_offset=end_offset_str
                                        )
                                    ),
                                    types.Part(text=prompt)
                                ]
                            ),
                            config=config
                        )
                        response_data = schema.model_validate_json(response.text).model_dump()
                        return response_data.get("explanation", "")
                    except (ValidationError, json.JSONDecodeError, asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"Chunk {start_offset_str}-{end_offset_str} attempt {attempt + 1} failed: {e}")
                        if attempt < MAX_RETRIES_CHUNK - 1:
                            await asyncio.sleep(delay_chunk)
                            delay_chunk *= 2
                        else:
                            logger.error(f"Chunk {start_offset_str}-{end_offset_str} failed after all retries.")
                            return ""  
                return ""

            tasks = []
            for start_time in range(0, duration, chunk_duration_seconds):
                end_time = min(start_time + chunk_duration_seconds, duration)
                tasks.append(_process_chunk_with_retry(start_time, end_time))

            logger.info(f"Starting to process {len(tasks)} video chunks concurrently.")
            chunk_responses = await asyncio.gather(*tasks)
            
            full_explanation = "\n".join(filter(None, chunk_responses))
            return full_explanation

    except Exception as e:
        logger.error(f"A critical error occurred in the main function: {e}")
        raise e
    finally:
        # FIX: Close clients safely
        if async_client:
            try:
                if hasattr(async_client, 'close'):
                    await async_client.close()
            except Exception as e:
                logger.debug(f"Async client close error (ignored): {e}")
        
        if client:
            try:
                client.close()
            except Exception as e:
                logger.warning(f"Sync client close error: {e}")
        
        await asyncio.sleep(0.25)


async def gemini_raw_edits_direct_video(
    video_list: list[str],
    schema: Type[BaseModel],
    prompt: str,
    old_file_variables:list,
    existing_file_names: List[str] = None
) -> dict[Any,Any]:

    uploaded_file_names = []
    files_variables = [] # This will hold ONLY types.Part objects now
    saving_uris=[]
    final_result = None
    error_occurred = None 
    model_name = 'gemini-2.5-pro'
    temperature = 0.4
    
    client = None
    async_client = None

    try:
        client = genai.Client(api_key=constants.GEMINI_API_KEY)
        async_client = client.aio 
        
        try:
            # ==========================================
            # 1. HANDLE EXISTING FILES
            # ==========================================
            if existing_file_names:
                logger.info(f"Found {len(existing_file_names)} existing Gemini files. Verifying availability...")
                
                valid_files = []
                for fname in existing_file_names:
                    try:
                        await async_client.files.get(name=fname)
                        valid_files.append(fname)
                    except Exception as e:
                        logger.warning(f"File {fname} expired or not found: {e}")
                
                if len(valid_files) == len(existing_file_names):
                    logger.info("All existing files verified. Skipping upload.")
                    uploaded_file_names = valid_files 
                    
                    # STRICT TYPE ENFORCEMENT: Create Part objects
                    files_variables =[]
                    for uri in old_file_variables:
                        part_obj = types.Part(
                                file_data=types.FileData(
                                    file_uri=uri,
                                    mime_type="video/mp4"
                                )
                            )
                        files_variables.append(part_obj)
                    saving_uris=old_file_variables

                else:
                    logger.warning("Some files expired. Re-uploading videos...")
                    existing_file_names = None

            # ==========================================
            # 2. HANDLE NEW UPLOADS
            # ==========================================
            if not existing_file_names:
                logger.info(f"Starting upload for {len(video_list)} files...")
                MAX_UPLOAD_RETRIES = 3
                files_to_wait_for = []

                for video_file_path in video_list:
                    if not os.path.exists(video_file_path):
                            raise FileNotFoundError(f"Input video file not found: {video_file_path}")
                    
                    logger.debug(f"Uploading: {video_file_path}")
                    
                    for attempt in range(MAX_UPLOAD_RETRIES):
                        try:
                            # Sync upload
                            video_variable = await asyncio.to_thread(client.files.upload, file=video_file_path)
                            
                            # FIX: Do NOT add the video_variable directly.
                            # Create a clean Part object using the URI.
                            part_obj = types.Part(
                                file_data=types.FileData(
                                    file_uri=video_variable.uri,
                                    mime_type=video_variable.mime_type # Use the mime type detected during upload
                                )
                            )
                            
                            files_variables.append(part_obj)
                            logger.info(f"file variables:{files_variables}")
                            saving_uris.append(video_variable.uri)
                            uploaded_file_names.append(video_variable.name)
                            files_to_wait_for.append(video_variable)
                            
                            logger.info(f"Successfully uploaded {video_file_path} on attempt {attempt + 1}")
                            break 

                        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                            logger.warning(f"Network error on upload attempt {attempt + 1}/{MAX_UPLOAD_RETRIES} for {video_file_path}: {e}")
                            if attempt < MAX_UPLOAD_RETRIES - 1:
                                await asyncio.sleep(2 * (attempt + 1))
                            else:
                                logger.error(f"Failed to upload {video_file_path} after {MAX_UPLOAD_RETRIES} attempts.")
                                raise e 
                
                logger.info("All files uploaded successfully.")
                
                # CRITICAL FIX: Wait for processing
                await _wait_for_files_active(async_client, files_to_wait_for)
            
            if not error_occurred:
                logger.info("Proceeding to content generation.")
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema, 
                    temperature=temperature
                )
                MAX_RETRIES_CHUNK = 3
                delay_chunk = 10
                
                # STRICT TYPE ENFORCEMENT: Wrap text in Part too
                text_part = types.Part(text=prompt)
                contents_to_send = files_variables + [text_part] 

                for attempt in range(MAX_RETRIES_CHUNK):
                    try:
                        logger.info(f"Attempting content generation {attempt + 1}/{MAX_RETRIES_CHUNK}...")
                        response = await async_client.models.generate_content(
                            model=model_name,
                            contents=contents_to_send,
                            config=config
                        )
                        logger.info(f"Received response on attempt {attempt + 1}.")
                        response_dict = schema.model_validate_json(response.text).model_dump()
                        logger.info(f"Successfully validated response on attempt {attempt + 1}.")
                        final_result = response_dict
                        error_occurred = None 
                        break 

                    except core_exceptions.InvalidArgument as e:
                        logger.error(f"Invalid argument: {e}")
                        error_occurred = e; break 
                    except core_exceptions.PermissionDenied as e:
                        logger.error(f"Invalid API Key: {e}")
                        error_occurred = e; break 
                    except core_exceptions.NotFound as e:
                        logger.error(f"Model not found: {e}")
                        error_occurred = e; break 

                    except (ValidationError, json.JSONDecodeError) as e:
                        logger.warning(f"Attempt {attempt + 1} validation error: {e}")
                        error_occurred = e 
                    except Exception as e:
                        logger.error(f"Attempt {attempt + 1} failed: {e}")
                        error_occurred = e 

                    if attempt < MAX_RETRIES_CHUNK - 1:
                        logger.info(f"Waiting {delay_chunk} seconds...")
                        await asyncio.sleep(delay_chunk)
                        delay_chunk *= 2
                    else:
                        logger.error(f"Failed after {MAX_RETRIES_CHUNK} retries.")

                if final_result is None and error_occurred is None:
                    error_occurred = RuntimeError(f"Failed to generate content after {MAX_RETRIES_CHUNK} retries.")

        except Exception as e:
            logger.error(f"Error in upload/generation block: {e}")
            error_occurred = e


    except Exception as e: 
        logger.error(f"Critical error: {e}")
        if error_occurred is None: 
            error_occurred = e

    finally:
        # FIX: Clean close logic with hasattr check
        if async_client:
            try:
                if hasattr(async_client, 'close'):
                    await async_client.close()
            except Exception as e:
                logger.debug(f"Error closing async client: {e}")
        
        if client:
            try:
                client.close()
            except Exception as e:
                logger.warning(f"Error closing sync client: {e}")

        # FIX: Yield to event loop to clear sockets
        try:
            await asyncio.sleep(0.5)
        except:
            pass

    if error_occurred:
        raise error_occurred 
    elif final_result is not None:
            logger.info("Function completed successfully.")

            return {
                "data": final_result,
                "active_files": uploaded_file_names,
                "files_variables":saving_uris
            }
    else:
            raise RuntimeError("Function finished unexpectedly.")
    


async def cleanup_gemini_files(file_names: List[str]):
    """
    Deletes a list of files from Google Gemini storage asynchronously.
    """
    if not file_names:
        logger.info("No files provided for cleanup.")
        return

    logger.info(f"🧹 Starting cleanup for {len(file_names)} Gemini files...")
    
    client = None
    async_client = None

    try:
        client = genai.Client(api_key=constants.GEMINI_API_KEY)
        async_client = client.aio

        tasks = []
        for name in file_names:
            logger.debug(f"Queueing deletion for: {name}")
            tasks.append(async_client.files.delete(name=name))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        for file_id, result in zip(file_names, results):
            if isinstance(result, Exception):
                if "404" in str(result) or "Not Found" in str(result):
                    logger.warning(f"File {file_id} was already deleted or not found.")
                else:
                    logger.error(f"Failed to delete {file_id}: {result}")
            else:
                success_count += 1

        logger.info(f"Cleanup complete. Successfully deleted {success_count}/{len(file_names)} files.")

    except Exception as e:
        logger.error(f"Critical error during cleanup initialization: {e}")

    finally:
        if async_client:
            try:
                if hasattr(async_client, 'close'):
                    await async_client.close()
            except Exception as e:
                logger.warning(f"Error closing async cleanup client: {e}")
        
        if client:
            try:
                client.close()
            except:
                pass
        
        # FIX: Yield to event loop
        await asyncio.sleep(0.25)
