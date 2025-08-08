#!/usr/bin/env python3

import subprocess

def list_audio_sources():
    """List available PulseAudio sources, marking system audio vs microphones"""
    try:
        print("Available PulseAudio sources:")
        sources_info = subprocess.run(["pactl", "list", "sources"], 
                                    capture_output=True, text=True).stdout
        
        # Parse sources, identifying monitors (system audio) vs inputs (mics)
        current_source = None
        monitor_sources = []
        mic_sources = []
        
        for line in sources_info.split('\n'):
            if line.startswith('Source #'):
                if current_source and 'name' in current_source:
                    # Store the previous source
                    name = current_source.get('name', '')
                    # Use name pattern to better identify source type
                    if 'alsa_input' in name:
                        current_source['is_monitor'] = "False"
                        mic_sources.append(current_source)
                    elif 'monitor' in name.lower() or 'alsa_output' in name:
                        current_source['is_monitor'] = "True"
                        monitor_sources.append(current_source)
                    elif current_source.get('is_monitor') == "True":
                        monitor_sources.append(current_source)
                    else:
                        mic_sources.append(current_source)
                
                # Start a new source
                current_source = {'id': line.split('#')[1].strip()}
                print(f"\nSource {current_source['id']}:")
            elif current_source is not None:
                if 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                    print(f"  Name: {current_source['name']}")
                    
                    # Pre-identify based on name pattern
                    name = current_source['name']
                    if 'alsa_input' in name:
                        current_source['is_monitor'] = "False"
                        print(f"  [MICROPHONE]")
                    elif 'monitor' in name.lower() or 'alsa_output' in name:
                        current_source['is_monitor'] = "True"
                        print(f"  [SYSTEM AUDIO]")
                elif 'monitor' in line.lower() and not current_source.get('is_monitor'):
                    current_source['is_monitor'] = "True"
                    print(f"  [SYSTEM AUDIO]")
                elif 'input' in line.lower() and 'Description:' in line and current_source.get('is_monitor') is None:
                    current_source['is_monitor'] = "False"
                    print(f"  [MICROPHONE]")
                elif 'State: ' in line:
                    state = line.split('State: ')[1].strip()
                    current_source['state'] = state
                    print(f"  State: {state}")
        
        # Process the last source
        if current_source and 'name' in current_source:
            name = current_source.get('name', '')
            if 'alsa_input' in name:
                current_source['is_monitor'] = "False"
                mic_sources.append(current_source)
            elif 'monitor' in name.lower() or 'alsa_output' in name:
                current_source['is_monitor'] = "True"
                monitor_sources.append(current_source)
            elif current_source.get('is_monitor') == "True":
                monitor_sources.append(current_source)
            else:
                mic_sources.append(current_source)
        
        print("\n=== Summary ===")
        print(f"System Audio Sources: {len(monitor_sources)}")
        for i, source in enumerate(monitor_sources):
            print(f"  {i+1}. {source['name']} ({source.get('state', 'unknown')})")
        
        print(f"Microphone Sources: {len(mic_sources)}")
        for i, source in enumerate(mic_sources):
            print(f"  {i+1}. {source['name']} ({source.get('state', 'unknown')})")
        
        print("\nTo use specific sources:")
        print("  For system audio: --source-system 'source_name'")
        print("  For microphone:   --source-mic 'source_name'")
    except Exception as e:
        print(f"Error listing sources: {e}")
        
    return monitor_sources, mic_sources

def find_system_audio_source():
    """Find the default system audio source"""
    try:
        monitor_sources, _ = get_audio_sources(verbose=False)
        
        # First check for any RUNNING sources
        for source in monitor_sources:
            if source.get('state') == 'RUNNING':
                return source['name']
        
        # If no running sources, return the first one
        if monitor_sources:
            return monitor_sources[0]['name']
    except Exception:
        pass
    
    return None

def find_microphone_source():
    """Find the default microphone source"""
    try:
        _, mic_sources = get_audio_sources(verbose=False)
        
        # First check for any RUNNING sources
        for source in mic_sources:
            if source.get('state') == 'RUNNING':
                return source['name']
        
        # If no running sources, return the first one
        if mic_sources:
            return mic_sources[0]['name']
    except Exception:
        pass
    
    return None

def get_audio_sources(verbose=False):
    """Get available audio sources categorized by type
    
    Returns:
        tuple: (monitor_sources, mic_sources) lists of source dictionaries
    """
    try:
        sources_info = subprocess.run(["pactl", "list", "sources"], 
                                    capture_output=True, text=True).stdout
        
        current_source = None
        monitor_sources = []
        mic_sources = []
        
        for line in sources_info.split('\n'):
            if line.startswith('Source #'):
                # Save previous source if exists
                if current_source and 'name' in current_source:
                    # Check the source name pattern to categorize
                    name = current_source.get('name', '')
                    if 'alsa_input' in name:
                        # Microphone source (input device)
                        current_source['is_monitor'] = "False"
                        mic_sources.append(current_source)
                    elif 'monitor' in name.lower() or 'alsa_output' in name:
                        # System audio source (output monitor)
                        current_source['is_monitor'] = "True"
                        monitor_sources.append(current_source)
                    # Fallback to existing classification
                    elif current_source.get('is_monitor') == "True":
                        monitor_sources.append(current_source)
                    else:
                        mic_sources.append(current_source)
                
                # Start new source
                current_source = {'id': line.split('#')[1].strip()}
            elif current_source is not None:
                if 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                    # Pre-identify based on name pattern
                    name = current_source['name']
                    if 'alsa_input' in name:
                        current_source['is_monitor'] = "False"
                    elif 'monitor' in name.lower() or 'alsa_output' in name:
                        current_source['is_monitor'] = "True"
                elif 'monitor' in line.lower() and 'alsa_output' in current_source.get('name', ''):
                    # Confirm monitor status for output devices
                    current_source['is_monitor'] = "True"
                elif 'Description:' in line and 'alsa_input' in current_source.get('name', ''):
                    # Confirm microphone status for input devices
                    current_source['is_monitor'] = "False"
                elif 'State: ' in line:
                    current_source['state'] = line.split('State: ')[1].strip()
        
        # Add the last source if exists
        if current_source and 'name' in current_source:
            name = current_source.get('name', '')
            if 'alsa_input' in name:
                current_source['is_monitor'] = "False"
                mic_sources.append(current_source)
            elif 'monitor' in name.lower() or 'alsa_output' in name:
                current_source['is_monitor'] = "True"
                monitor_sources.append(current_source)
            elif current_source.get('is_monitor') == "True":
                monitor_sources.append(current_source)
            else:
                mic_sources.append(current_source)
        
        if verbose:
            print(f"Found {len(monitor_sources)} system audio sources and {len(mic_sources)} microphone sources")
        
        return monitor_sources, mic_sources
    except Exception as e:
        if verbose:
            print(f"Error getting audio sources: {e}")
        return [], []

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

if __name__ == "__main__":
    # If run directly, list available audio sources
    if check_dependencies():
        list_audio_sources()
