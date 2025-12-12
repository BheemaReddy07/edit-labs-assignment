from pydantic import BaseModel,Field
from typing import List
from datetime import timedelta

class ReferenceVideoResponseSchema(BaseModel):
    explanation:str=Field(description="The technical explanation of all the editing techniques including the sound effects, colour grading,cuts, transitions,B-Rolls and visulas,animations,colour effects etc.")


class EditSchema(BaseModel):
    sequence_index: int = Field(..., description="The order of this segment in the final edited sequence (starting from 1).")
    source_video_index: int = Field(..., description="The index(1,2,3,4,....) of the raw input video file from which this segment originates. i.e if the segment is from the first video uploaded then it should be 1, second video then 2 and so on.")
    source_video_name:str =Field(...,description="The name of the video of raw input video file from which this segment originates")
    start_time:timedelta=Field(description="the time stamp where the required edit begings in the video attached.")
    end_time:timedelta=Field(description="the time stamp where the required edit ends in the video attached")
    duration_seconds:int=Field(description="The number of seconds of to be focused on in the raw video.")
    source_shot_description:str=Field(description="The description of the shot we are working on currently that is in between the timestamps.")
    speed_to_be_kept:str=Field(description="The speed of the video to be kept in this particular shot like normal,fast,slow motion or etc.")
    edit_to_be_done:str=Field(description="The edits, cuts,B-rools,transition,animations, graphics and all the other edits that need to be done to for this particular shot along with the reframing, cropping, or repositioning to make the important content effective in the vertical 9:16 aspect ratio.")
    music_description:str=Field(description="The description of the music mix that is to be done in these time stamps along with intensity, style and action(eg:stop or continue or etc.)")
    colour_description:str=Field(description="The description of the colour grading needed at this particular shot and how to take on from previous shots and pass to next shots.")
    notes:str=Field(description="The text to be displayed on the screen along with the text description like font,style,colour and more specification and return \'NONE\' if not needed any text")


class RawVideoResponseSchema(BaseModel):
    all_edits:List[EditSchema]=Field(description="list of all the edit jsons each containing start_time,end_time,duration_seconds,shot_description,music_description,colour_description,notes")
