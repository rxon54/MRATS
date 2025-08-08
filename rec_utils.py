#!/usr/bin/env python3

import subprocess
import os
from datetime import datetime
import json

def check_dependencies():
    """Check if required tools are installed"""
    tools_missing = False
    
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: ffmpeg is not installed. Please install it with:")
        print("  sudo apt-get install ffmpeg")
        tools_missing = True
    
    try:
        subprocess.run(["pactl", "--version"], check=True, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: PulseAudio utils not installed. Please install with:")
        print("  sudo apt-get install pulseaudio-utils")
        tools_missing = True
    
    return not tools_missing

def list_sources():
    """Redirect to audio_sources module"""
    from audio_sources import list_audio_sources
    list_audio_sources()


def save_recording_metadata(output_path, metadata):
    """Save recording metadata to a JSON file alongside the recording"""
    try:
        # Create metadata file path by replacing audio extension with .json
        base_path = os.path.splitext(output_path)[0]
        metadata_path = f"{base_path}.json"
        
        # Ensure any non-serializable types are converted to strings
        for key, value in metadata.items():
            if not isinstance(value, (str, int, float, bool, type(None), list, dict)):
                metadata[key] = str(value)
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return True
    except Exception as e:
        print(f"Error saving metadata: {e}")
        return False

def get_file_duration(file_path):
    """Get the duration of an audio file in seconds using ffprobe"""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting file duration: {e}")
    
    return None

def get_file_size_mb(file_path):
    """Get the file size in MB"""
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)  # Convert to MB
    except Exception:
        return None

def post_process_audio(input_file, output_file=None, noise_reduce=False, normalize=False, enhance_speech=False):
    """Apply post-processing effects to an audio file
    
    Args:
        input_file (str): Path to input audio file
        output_file (str, optional): Path to output file. If None, will modify input file
        noise_reduce (bool): Apply noise reduction
        normalize (bool): Apply normalization
        enhance_speech (bool): Apply speech enhancement
        
    Returns:
        bool: True if successful, False otherwise
    """
    if output_file is None:
        # Create temp file
        base_path = os.path.splitext(input_file)[0]
        ext = os.path.splitext(input_file)[1]
        output_file = f"{base_path}_processed{ext}"
    
    try:
        ffmpeg_args = ["ffmpeg", "-y", "-i", input_file]
        filter_parts = []
        
        # Add requested filters
        if noise_reduce:
            filter_parts.append("afftdn=nf=-25")
        
        if normalize:
            filter_parts.append("loudnorm=I=-16:LRA=11:TP=-1.5")
        
        if enhance_speech:
            filter_parts.append("highpass=f=200,lowpass=f=3000,equalizer=f=1000:width_type=o:width=1:g=3")
        
        # Add filter complex if we have any filters
        if filter_parts:
            ffmpeg_args.extend(["-af", ",".join(filter_parts)])
        
        # Add output file
        ffmpeg_args.append(output_file)
        
        # Run command
        result = subprocess.run(ffmpeg_args, capture_output=True, text=True)
        
        if result.returncode == 0:
            # If we're modifying the original file, replace it now
            if output_file != input_file and os.path.exists(output_file):
                os.replace(output_file, input_file)
                return True
            return True
        else:
            print(f"Error in post-processing: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error post-processing audio: {e}")
        return False
