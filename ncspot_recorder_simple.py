#!/usr/bin/env python3

import os
import time
import signal
import argparse
import subprocess
import sys
import threading
from datetime import datetime
from rec_utils import check_dependencies, list_sources

class NcspotRecorder:
    def __init__(self, output_dir="~/Music/ncspot_recordings", format="mp3", bitrate="192k", 
                monitor_interval=60, smart_cut=True, source=None, playlist_mode=False):
        # Initialize configuration
        self.output_dir = os.path.expanduser(output_dir)
        self.format = format
        self.bitrate = bitrate
        self.monitor_interval = monitor_interval
        self.smart_cut = smart_cut
        self.audio_source = source
        self.playlist_mode = playlist_mode
        self.playlist_folder = None
        if self.playlist_mode:
            self.playlist_folder = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize state variables
        self.ffmpeg_process = None
        self.current_track = None
        self.recording = False
        self.track_started = None
        self.end_timer = None
        self.snap_ncspot = False
        self.no_id3 = False  # Enable ID3 tagging by default
        
        # Setup
        os.makedirs(self.output_dir, exist_ok=True)
        if "/snap/ncspot" in subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout:
            print("Detected ncspot running as a Snap package")
            self.snap_ncspot = True
            
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Log file for recorded tracks
        self.log_file = os.path.join(self.output_dir, "recorded_tracks.log")
        # Ensure log file exists and is not overwritten
        if not os.path.exists(self.log_file):
            with open(self.log_file, "a") as f:
                pass
    
    def debug(self, msg):
        now = datetime.now().strftime("[%b-%d %H:%M:%S]")
        print(f"{now} {msg}")

    def signal_handler(self, sig, frame):
        print("\nShutting down recorder...")
        self.stop_recording()
        sys.exit(0)
        
    def get_playerctl_metadata(self, key):
        player_arg = ["-p", "ncspot"]
        result = subprocess.run(["playerctl", *player_arg, "metadata", key], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def get_current_track(self):
        """Get current track metadata using playerctl"""
        try:
            player_arg = ["-p", "ncspot"]
            result = subprocess.run(["playerctl", *player_arg, "status"], capture_output=True, text=True)
            if result.returncode != 0:
                # Try alternative approach for snap packages
                if self.snap_ncspot:
                    snap_info = self.get_track_from_snap()
                    return snap_info, "Playing" if snap_info else "Stopped"
                return None, "Stopped"
                
            status = result.stdout.strip()
            if status != "Playing":
                return None, status
                
            # Collect basic track information
            track = {
                "artist": self.get_playerctl_metadata("xesam:artist") or "Unknown Artist",
                "title": self.get_playerctl_metadata("xesam:title") or "Unknown Track",
                "length_us": 0
            }
            
            # Collect additional metadata from MPRIS
            album = self.get_playerctl_metadata("xesam:album")
            if album:
                track["album"] = album
                
            album_artist = self.get_playerctl_metadata("xesam:albumArtist")
            if album_artist:
                track["album_artist"] = album_artist
                
            # Fix: Use xesam namespace prefix for track number
            track_number = self.get_playerctl_metadata("xesam:trackNumber")
            if track_number:
                try:
                    track["track_number"] = int(track_number)
                except ValueError:
                    pass
                    
            disc_number = self.get_playerctl_metadata("xesam:discNumber")
            if disc_number:
                try:
                    track["disc_number"] = int(disc_number)
                except ValueError:
                    pass
                    
            # Try to get year from metadata
            date = self.get_playerctl_metadata("xesam:contentCreated")
            if date and len(date) >= 4:
                track["year"] = date[:4]  # Extract year from date string
                
            genre = self.get_playerctl_metadata("xesam:genre")
            if genre:
                track["genre"] = genre
                
            # Try to get URL for the track
            url = self.get_playerctl_metadata("xesam:url")
            if url:
                track["url"] = url
                
            # Get artwork URL if available
            art_url = self.get_playerctl_metadata("mpris:artUrl")
            if art_url:
                track["art_url"] = art_url
                
            # Get track length
            length_str = self.get_playerctl_metadata("mpris:length")
            if length_str:
                try:
                    track["length_us"] = int(length_str)
                    # Only print debug for track length and name if this is a new track
                    if not self.current_track or self.current_track["id"] != f"{track['artist']}-{track['title']}":
                        total_sec = int(track['length_us'] / 1000000)
                        mm = total_sec // 60
                        ss = total_sec % 60
                        self.debug(f"Track length: {mm:02d}:{ss:02d} minutes")
                        self.debug(f"Current track: {track['artist']} - {track['title']}")
                        
                        # Print additional metadata for debugging
                        for key, value in track.items():
                            if key not in ["artist", "title", "length_us", "id"]:
                                self.debug(f"Metadata - {key}: {value}")
                except Exception:
                    pass
            
            track["id"] = f"{track['artist']}-{track['title']}"
            return track, status
            
        except Exception as e:
            self.debug(f"Error getting track info: {e}")
            return None, "Unknown"
    
    def get_track_from_snap(self):
        """Fallback: Try to get track info from process list"""
        try:
            output = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
            
            for line in output.split('\n'):
                if 'ncspot' in line and '|' in line:
                    track_part = line.split('|')[0].strip()
                    if ' - ' in track_part:
                        artist, title = track_part.split(' - ', 1)
                        return {
                            "id": f"{artist}-{title}",
                            "artist": artist,
                            "title": title,
                            "length_us": 0
                        }
            
            return None
        except Exception:
            return None
    
    def get_audio_source(self):
        """Find the best audio source for recording"""
        if self.audio_source:
            return ["-f", "pulse", "-i", self.audio_source]
            
        try:
            # Try to find a monitor source
            sources_info = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True).stdout
            
            monitor_sources = []
            current_source = None
            
            for line in sources_info.split('\n'):
                if line.startswith('Source #'):
                    current_source = {}
                elif current_source is not None and 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                elif current_source is not None and 'monitor' in line.lower():
                    monitor_sources.append(current_source['name'])
            
            if monitor_sources:
                source_name = monitor_sources[0]
                self.debug(f"Using PulseAudio monitor source: {source_name}")
                return ["-f", "pulse", "-i", source_name]
                
        except Exception as e:
            self.debug(f"Error finding audio source: {e}")
        
        # Default fallback
        return ["-f", "pulse", "-i", "default"]
    
    def log_recording(self, path):
        """Log the recorded track path to the log file"""
        try:
            with open(self.log_file, "a") as f:
                f.write(path + "\n")
        except Exception as e:
            self.debug(f"Failed to log recording: {e}")

    def start_recording(self, track_info):
        """Start recording the current track"""
        if self.ffmpeg_process:
            self.stop_recording()
        # Do NOT rewind the track anymore
        artist = track_info.get('artist', 'Unknown Artist').strip() or 'Unknown Artist'
        album = track_info.get('album', self.get_playerctl_metadata("album") or "Unknown Album")
        album = album.strip() or "Unknown Album"
        title = track_info.get('title', 'Unknown Track').strip() or 'Unknown Track'
        # Sanitize directory and filename
        for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            artist = artist.replace(char, '_')
            album = album.replace(char, '_')
            title = title.replace(char, '_')
        if self.playlist_mode:
            if not self.playlist_folder:
                self.playlist_folder = datetime.now().strftime("%Y%m%d_%H%M%S")
            dir_path = os.path.join(self.output_dir, str(self.playlist_folder))
            os.makedirs(dir_path, exist_ok=True)
            filename = f"{artist} - {title}.{self.format}"
        else:
            dir_path = os.path.join(self.output_dir, artist, album)
            os.makedirs(dir_path, exist_ok=True)
            filename = f"{artist} - {title}.{self.format}"
        output_path = os.path.join(dir_path, filename)
        
        # Get audio input arguments
        input_args = self.get_audio_source()
        
        try:
            # Build ffmpeg command
            cmd = [
                "ffmpeg", "-v", "warning", "-stats", *input_args,
                "-c:a", "libmp3lame" if self.format == "mp3" else "pcm_s16le",
                "-b:a", self.bitrate, "-y", output_path
            ]
            
            print(f"Recording: {artist} - {title}")
            self.debug(f"Output: {output_path}")
            
            # Start recording process
            self.ffmpeg_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Check if process started correctly
            time.sleep(1)
            if self.ffmpeg_process.poll() is not None:
                print(f"Error: ffmpeg failed to start (exit code {self.ffmpeg_process.returncode})")
                return False
            
            # Store output path for ID3 tagging after recording is complete
            track_info['_output_path'] = output_path
            self.current_track = track_info
            self.recording = True
            self.track_started = time.time()
            self.log_recording(output_path)
            
            # If smart cut is enabled and we have track length, use precise cut
            if self.smart_cut and track_info.get('length_us', 0) > 0:
                length_sec = track_info['length_us'] / 1000000
                buffer = 2.0
                end_time = max(length_sec - buffer, 0)
                mm = int(length_sec) // 60
                ss = int(length_sec) % 60
                self.debug(f"Precise cut: Will enter precise window at {end_time:.2f}s, track length {mm:02d}:{ss:02d}")
                if self.end_timer:
                    self.end_timer.cancel()
                self.end_timer = threading.Timer(end_time, self.precise_cut_window, args=(track_info,))
                self.end_timer.daemon = True
                self.end_timer.start()
            return True
        except Exception as e:
            print(f"Error starting recording: {e}")
            return False

    def precise_cut_window(self, track_info):
        self.debug("Precise cut: Entering final window, polling for track change every 100ms")
        current_id = track_info["id"]
        while self.recording:
            tinfo, status = self.get_current_track()
            if not self.recording:
                break
            if status != 'Playing' or not tinfo or tinfo["id"] != current_id:
                self.debug("Precise cut: Track changed, stopping recording")
                self.stop_recording()
                # Start next track if available
                tinfo2, status2 = self.get_current_track()
                if status2 == 'Playing' and tinfo2 and tinfo2["id"] != current_id:
                    self.debug("Precise cut: Starting recording of next track")
                    self.start_recording(tinfo2)
                break
            time.sleep(0.1)
    
    def stop_recording(self):
        """Stop the current recording"""
        if not self.ffmpeg_process:
            return
        now = datetime.now().strftime("[%b-%d %H:%M:%S]")
        print(f"{now} Stopping recording...")
        
        # Cancel any scheduled end timer
        if self.end_timer:
            self.end_timer.cancel()
            self.end_timer = None
        
        # Store track info for ID3 tagging
        current_track = self.current_track
        
        # Terminate ffmpeg process
        self.ffmpeg_process.terminate()
        try:
            self.ffmpeg_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Warning: ffmpeg process didn't exit, forcing termination")
            self.ffmpeg_process.kill()
        
        self.ffmpeg_process = None
        self.recording = False
        self.track_started = None
        print(f"{now} Recording stopped")
        
        # Add ID3 tags if this is an MP3 file and we have track info and ID3 tagging is enabled
        if not self.no_id3 and current_track and '_output_path' in current_track and self.format == "mp3":
            output_path = current_track['_output_path']
            try:
                # Import here to avoid errors if mutagen is not available
                from rec_utils import add_id3_tags
                
                self.debug(f"Adding ID3 tags to {os.path.basename(output_path)}")
                success = add_id3_tags(output_path, current_track)
                if success:
                    self.debug("ID3 tags added successfully")
                else:
                    self.debug("Failed to add ID3 tags")
            except ImportError:
                self.debug("ID3 tagging skipped (mutagen not available)")
            except Exception as e:
                self.debug(f"Error adding ID3 tags: {e}")
    
    def smart_cut_recording(self):
        """End recording based on track length rather than track change"""
        if not self.recording:
            return
            
        self.debug("Smart cut: Ending recording based on track length")
        self.stop_recording()
        
        # Try to immediately start recording the next track
        track_info, status = self.get_current_track()
        if status == 'Playing' and track_info:
            if not self.current_track or self.current_track["id"] != track_info["id"]:
                self.debug("Smart cut: Starting recording of next track")
                self.start_recording(track_info)
    
    def check_and_record(self):
        """Check for currently playing track and start recording if needed"""
        track_info, status = self.get_current_track()
        
        if status == 'Playing' and track_info:
            # If we have a new track, start recording
            if not self.current_track or self.current_track["id"] != track_info["id"]:
                print("New track detected, starting recording")
                if self.recording:
                    self.stop_recording()
                time.sleep(0.5)  # Slight delay to ensure track started
                self.start_recording(track_info)
            elif not self.recording:
                # Same track but not recording (paused and resumed)
                print("Same track resumed, starting recording")
                self.start_recording(track_info)
        elif status != 'Playing' and self.recording:
            # Stop recording if track is not playing
            print("Track not playing, stopping recording")
            self.stop_recording()
    
    def run(self):
        """Main loop for the recorder"""
        print(f"ncspot Recorder started - saving to {self.output_dir}")
        print("Waiting for ncspot to play a track...")
        print("Press Ctrl+C to exit")
        
        if self.smart_cut:
            # Only check once at start, then let smart_cut timers handle track changes
            while True:
                self.check_and_record()
                time.sleep(2)
        else:
            try:
                while True:
                    self.check_and_record()
                    time.sleep(self.monitor_interval)
            except KeyboardInterrupt:
                print("Exiting...")
                self.stop_recording()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record tracks played by ncspot")
    parser.add_argument("--output", "-o", default="~/Music/ncspot_recordings", 
                        help="Output directory for recordings")
    parser.add_argument("--format", "-f", default="mp3", choices=["mp3", "wav"], 
                        help="Audio format for recordings")
    parser.add_argument("--bitrate", "-b", default="192k", 
                        help="Bitrate for audio encoding (for mp3)")
    parser.add_argument("--source", "-s", help="Specify PulseAudio source directly")
    parser.add_argument("--list-sources", "-l", action="store_true",
                        help="List available PulseAudio sources and exit")
    parser.add_argument("--monitor-interval", "-i", type=int, default=3,
                        help="Check interval in seconds (1-10, default: 3)")
    parser.add_argument("--smart-cut", action="store_true", default=True,
                        help="Use track length for timing (default: enabled)")
    parser.add_argument("--no-smart-cut", action="store_false", dest="smart_cut",
                        help="Wait for track changes instead of using track length")
    parser.add_argument("--playlist-mode", "-p", action="store_true", 
                        help="Save all tracks in a single folder named by date_time (no artist/album structure)")
    parser.add_argument("--no-id3", action="store_true",
                        help="Disable ID3 tag writing for MP3 files")
    args = parser.parse_args()
    if args.list_sources:
        list_sources()
        sys.exit(0)
    if not check_dependencies():
        sys.exit(1)
    recorder = NcspotRecorder(
        output_dir=args.output,
        format=args.format,
        bitrate=args.bitrate,
        monitor_interval=args.monitor_interval,
        smart_cut=args.smart_cut,
        source=args.source,
        playlist_mode=args.playlist_mode
    )
    
    # Set no_id3 flag if specified
    if args.no_id3:
        recorder.no_id3 = True
        print("ID3 tagging disabled")
    else:
        recorder.no_id3 = False
    def manual_check_handler(sig, frame):
        print("\nManual check triggered...")
        recorder.check_and_record()
    signal.signal(signal.SIGUSR1, manual_check_handler)
    print(f"Tip: Send SIGUSR1 to trigger manual check: kill -USR1 {os.getpid()}")
    recorder.run()
