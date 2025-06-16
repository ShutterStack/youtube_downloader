import streamlit as st
import yt_dlp
import os
import shutil
import tempfile
import re
import time
import glob # Import glob for file searching
import shutil # Add this import at the top with other imports

# --- Configuration ---
TEMP_DIR = "temp_downloads"
MAX_FILE_SIZE_MB = 500
# Ensure ffmpeg_location is correctly set for your system
# IMPORTANT: Adjust this path if your ffmpeg.exe is located elsewhere!
# On Windows, it should point directly to ffmpeg.exe
# On Linux/macOS, it's usually just 'ffmpeg' if it's in your PATH, or a full path like '/usr/bin/ffmpeg'
FFMPEG_LOCATION = '/usr/bin/ffmpeg' if os.name != 'nt' else r'C:\Users\admin\Documents\ffmpeg\bin\ffmpeg.exe' # Adjusted for Windows based on your logs


# --- Helper Functions ---
def create_temp_dir():
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)

def clean_temp_dir():
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
            st.toast("Cleaned up temporary files! ✅", icon="🧹")
            os.makedirs(TEMP_DIR)
        except OSError as e:
            st.warning(f"Error cleaning up temp directory: {e}")
    else:
        os.makedirs(TEMP_DIR)

# Ensure temp directory exists at app startup
create_temp_dir()

# Sanitize filenames for various OS compatibility
def sanitize_filename(filename):
    # Remove characters illegal in Windows filenames, and trim leading/trailing spaces/dots
    cleaned_filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Replace sequences of dots at the end (common issue with some filenames)
    cleaned_filename = re.sub(r'\.+$', '', cleaned_filename)
    return cleaned_filename.strip() # Remove leading/trailing whitespace

# Cache content info (video or playlist) to avoid re-fetching on every rerun
@st.cache_data(show_spinner="Fetching content information...")
def get_content_info(url):
    info = None # Initialize info to None
    try:
        ydl_opts = {
            'noplaylist': False, # Allow playlists
            'quiet': True,
            'skip_download': True,
            'format': 'all',
            'force_generic_extractor': True,
            'retries': 3,
            'extract_flat': False, # Crucial for getting full info for entries in a playlist
            'ignore_errors': True # This ensures playlist processing continues even with unavailable videos
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                # If info is None even with ignore_errors, it means URL might be invalid or completely inaccessible
                st.error("Could not retrieve any information for the provided URL. It might be invalid or completely unavailable.")
                return {'title': 'Content Not Found', 'webpage_url': url, '_type': 'video'}, False, []

            is_playlist = info.get('_type') == 'playlist'
            
            if is_playlist:
                entries = info.get('entries', [])
                # Filter out None entries and entries marked as explicitly unavailable/private
                # yt-dlp might return None for some entries if they're unavailable/deleted
                # or an entry dictionary with 'availability': 'unavailable'
                valid_entries = [e for e in entries if e is not None and e.get('availability') not in ['private', 'unlisted', 'unavailable']]
                return info, is_playlist, valid_entries # main playlist info, True, list of video infos
            else:
                return info, is_playlist, [info] # main video info, False, list containing single video info

    except yt_dlp.utils.DownloadError as e:
        st.error(f"Error fetching content info for {url}: {e}")
        # Create a minimal info dict to allow the app to continue without crashing
        # and display a message that content is unavailable.
        error_info = info if info else {
            'title': 'Content Unavailable/Error', 
            'webpage_url': url, 
            '_type': 'video' # Default to video type if original type is unknown due to error
        }
        # Heuristic: if URL contains 'playlist', try to set type to playlist
        if 'playlist' in url.lower() and not error_info.get('_type') == 'video':
             error_info['_type'] = 'playlist'

        return error_info, error_info.get('_type') == 'playlist', [] # Return empty entries list on error
    except Exception as e:
        st.error(f"An unexpected error occurred for {url}: {e}")
        error_info = info if info else {
            'title': 'An Error Occurred', 
            'webpage_url': url, 
            '_type': 'video'
        }
        if 'playlist' in url.lower() and not error_info.get('_type') == 'video':
             error_info['_type'] = 'playlist'
        return error_info, error_info.get('_type') == 'playlist', []


# Function to dynamically generate download options based on desired output type
def generate_download_options(info, output_type):
    options = []
    
    # Check if 'formats' key exists and is not None
    if not info or 'formats' not in info or not info['formats']:
        return [] # No formats available

    # Sort formats by quality (higher resolution first, then higher fps)
    formats = sorted(info['formats'], key=lambda f: (
        f.get('height') or 0, 
        f.get('fps') or 0, 
        f.get('tbr') or 0 # Total bitrate
    ), reverse=True)

    if output_type == 'mp4':
        # Add "Best Video + Best Audio (Merged MP4 - Recommended)" option at the top
        options.append({
            'label': 'Best Video + Best Audio (Merged MP4 - Recommended)',
            'format_id': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio', # Prioritize mp4+m4a, fallback to any best
            'is_merged': True,
            'ext': 'mp4', # Explicitly set expected output extension
            'vcodec': 'best',
            'acodec': 'aac (re-encoded)',
            'resolution': 'best'
        })

        # Add "Video + Audio (Merged)" options for specific MP4 qualities
        merged_video_qualities = set()
        for f in formats:
            # Filter for video-only MP4 formats that have a height, and haven't been added yet
            if (f.get('vcodec') != 'none' and f.get('acodec') == 'none' and 
                f.get('ext') == 'mp4' and f.get('height') and f.get('height') not in merged_video_qualities):
                options.append({
                    'label': f"Video {f['height']}p ({f['ext']}) + Best Audio (Merged MP4)",
                    'format_id': f"{f['format_id']}+bestaudio",
                    'is_merged': True,
                    'ext': 'mp4', # Explicitly set expected output extension
                    'vcodec': f.get('vcodec'),
                    'acodec': 'aac (re-encoded)', # Indicate it will be re-encoded
                    'resolution': f.get('resolution')
                })
                merged_video_qualities.add(f['height'])
        
        # Add "Video Only" options (MP4 and WebM)
        video_only_options = []
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('acodec') == 'none' and f.get('ext') in ['mp4', 'webm']:
                label = f"Video Only {f.get('resolution', '')} ({f.get('ext')}, {f.get('vcodec')})"
                video_only_options.append({
                    'label': label,
                    'format_id': f['format_id'],
                    'is_merged': False,
                    'ext': f['ext'], # Explicitly set expected output extension
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec'),
                    'resolution': f.get('resolution')
                })
        options.extend(video_only_options)

    elif output_type == 'mp3':
        # Add a general "Best Audio (Converted to MP3 - Recommended)" option
        options.append({
            'label': 'Best Audio (Converted to MP3 - Recommended)',
            'format_id': 'bestaudio',
            'is_merged': False,
            'ext': 'mp3',
            'vcodec': 'none',
            'acodec': 'mp3 (re-encoded)',
            'resolution': 'N/A'
        })
        # Add "Audio Only" options for MP3 output
        audio_only_options = []
        for f in formats:
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none': # Ensure it's truly audio-only
                label = f"Audio Only ({f.get('acodec', '')}, {f.get('abr', 0)}kbps)"
                audio_only_options.append({
                    'label': label,
                    'format_id': f['format_id'],
                    'is_merged': False, # Even if it's bestaudio, it's not merged video+audio
                    'ext': 'mp3', # Explicitly set expected output extension (due to postprocessor)
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec'),
                    'resolution': f.get('resolution')
                })
        options.extend(audio_only_options)
    
    return options

# Global variable for debug logging of filepath from hook
download_complete_filepath_from_hook = None 

# Callback for download progress - now primarily for UI updates and debug logging
def update_progress(d, status_placeholder, progress_bar):
    global download_complete_filepath_from_hook 
    if d['status'] == 'downloading':
        p = d.get('_percent_str', '0%').replace(' ', '')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        status_placeholder.text(f"Downloading: {p} at {speed} ETA: {eta}")
        try:
            progress_bar.progress(float(d.get('_percent_str', '0%').strip('%')) / 100)
        except ValueError:
            pass # Ignore if percentage string is not yet a valid float
    elif d['status'] == 'finished':
        progress_bar.progress(1.0) # Ensure it reaches 100%
        # Capture the actual final filepath for debug logging
        if 'filepath' in d:
            download_complete_filepath_from_hook = d['filepath']
            print(f"DEBUG: Filepath captured from finished hook: {download_complete_filepath_from_hook}")
        else:
            print("DEBUG: 'filepath' not found in finished hook data.")


# Function to download a single content (video)
def download_content(url, selected_option, info, status_placeholder, progress_bar):
    global download_complete_filepath_from_hook
    download_complete_filepath_from_hook = None # Reset at the start of each download

    try:
        sanitized_title = sanitize_filename(info.get('title', 'video'))
        
        if selected_option['is_merged']:
            output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}.%(ext)s")
        else:
            output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}_%(format_id)s.%(ext)s")

        ydl_opts = {
            'outtmpl': output_filename_template,
            'progress_hooks': [lambda d: update_progress(d, status_placeholder, progress_bar)],
            'ffmpeg_location': FFMPEG_LOCATION,
            'retries': 3,
            'verbose': True,
            'compat_opts': set(),
            'noplaylist': True, # Ensure only single video is downloaded from this instance
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.74 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            }
        }

        if selected_option['is_merged']:
            ydl_opts['format'] = selected_option['format_id']
            ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts['postprocessors'] = [
                {'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'},
            ]
        elif selected_option['ext'] == 'mp3':
            ydl_opts['format'] = selected_option['format_id']
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = selected_option['format_id']

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url]) # Execute the download. Hooks will run.
            
            # --- Robust File Path Discovery ---
            final_downloaded_path_to_check = None
            sanitized_title_for_glob = sanitize_filename(info.get('title', 'video'))

            if selected_option['is_merged']:
                expected_ext = 'mp4'
                matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}*.{expected_ext}"))
                exact_match = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                if exact_match in matching_files:
                    final_downloaded_path_to_check = exact_match
                elif matching_files:
                    final_downloaded_path_to_check = matching_files[0]
            else:
                expected_ext = selected_option['ext']
                matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}_*.{expected_ext}"))
                if matching_files:
                    final_downloaded_path_to_check = max(matching_files, key=os.path.getmtime) # Get most recent
                else:
                    simple_name_path = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                    if os.path.exists(simple_name_path):
                        final_downloaded_path_to_check = simple_name_path

            print(f"DEBUG: Final path determined by glob search: {final_downloaded_path_to_check}")

            if final_downloaded_path_to_check and os.path.exists(final_downloaded_path_to_check):
                st.session_state.downloaded_files.append(final_downloaded_path_to_check) # Append to list
                status_placeholder.success(f"Download complete: {os.path.basename(final_downloaded_path_to_check)}")
            else:
                status_placeholder.error(f"Download completed, but file not found at: {final_downloaded_path_to_check}. This may indicate an unexpected filename or an issue with file creation/deletion by yt-dlp/ffmpeg. Please check console for more errors.")

    except yt_dlp.utils.DownloadError as e:
        status_placeholder.error(f"Download Error: {e}")
        st.error("Failed to download. Check the console/logs for details.")
    except Exception as e:
        status_placeholder.error(f"An unexpected error occurred: {e}")
        st.error("Failed to download. Check the console/logs for details.")


# Function to download multiple contents (for playlists)
def download_content_for_playlist(selected_entries, selected_option, status_placeholder, progress_bar):
    total_videos = len(selected_entries)
    if total_videos == 0:
        status_placeholder.warning("No videos selected for download.")
        return

    st.session_state.downloaded_files = [] # Clear previous downloads for playlist
    
    for i, entry_info in enumerate(selected_entries):
        if not entry_info: # Skip None entries (e.g., private/deleted videos in a playlist)
            status_placeholder.info(f"Skipping empty entry {i+1} in playlist.")
            continue

        video_url = entry_info.get('webpage_url')
        # Also check for 'availability' directly from the entry_info
        if not video_url or entry_info.get('availability') in ['private', 'unlisted', 'unavailable', 'removed_by_youtube', 'removed_by_user']:
            title_display = entry_info.get('title', 'Untitled Video')
            status_placeholder.warning(f"Skipping video {i+1}: '{title_display}' is unavailable or URL not found.")
            continue

        status_placeholder.text(f"Downloading video {i+1}/{total_videos}: {entry_info.get('title', '...')}")
        # Update overall playlist progress by number of videos processed
        progress_bar.progress((i / total_videos)) 

        # Reset hook global for each video download (mostly for debug logging)
        global download_complete_filepath_from_hook
        download_complete_filepath_from_hook = None

        try:
            sanitized_title = sanitize_filename(entry_info.get('title', 'video'))
            
            if selected_option['is_merged']:
                output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}.%(ext)s")
            else:
                output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}_%(format_id)s.%(ext)s")

            ydl_opts = {
                'outtmpl': output_filename_template,
                'progress_hooks': [lambda d: update_progress(d, status_placeholder, progress_bar)],
                'ffmpeg_location': FFMPEG_LOCATION,
                'retries': 3,
                'verbose': True,
                'compat_opts': set(),
                'noplaylist': True, # Crucial: ensure only this single video is downloaded by this YDL instance
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.74 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate'
                }
            }

            if selected_option['is_merged']:
                ydl_opts['format'] = selected_option['format_id']
                ydl_opts['merge_output_format'] = 'mp4'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}]
            elif selected_option['ext'] == 'mp3':
                ydl_opts['format'] = selected_option['format_id']
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
            else:
                ydl_opts['format'] = selected_option['format_id']

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url]) # Download the current video in the loop

                # --- Robust File Path Discovery for the current video ---
                final_downloaded_path_to_check = None
                sanitized_title_for_glob = sanitize_filename(entry_info.get('title', 'video'))

                if selected_option['is_merged']:
                    expected_ext = 'mp4'
                    matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}*.{expected_ext}"))
                    exact_match = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                    if exact_match in matching_files:
                        final_downloaded_path_to_check = exact_match
                    elif matching_files:
                        final_downloaded_path_to_check = matching_files[0] # Take the first match
                else:
                    expected_ext = selected_option['ext']
                    matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}_*.{expected_ext}"))
                    if matching_files:
                        final_downloaded_path_to_check = max(matching_files, key=os.path.getmtime) # Get most recent
                    else:
                        simple_name_path = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                        if os.path.exists(simple_name_path):
                            final_downloaded_path_to_check = simple_name_path

                if final_downloaded_path_to_check and os.path.exists(final_downloaded_path_to_check):
                    st.session_state.downloaded_files.append(final_downloaded_path_to_check)
                    status_placeholder.text(f"Downloaded: {os.path.basename(final_downloaded_path_to_check)} ({i+1}/{total_videos})")
                else:
                    status_placeholder.error(f"Failed to find downloaded file for {entry_info.get('title', 'Untitled')} at {final_downloaded_path_to_check}")

        except yt_dlp.utils.DownloadError as e:
            status_placeholder.error(f"Error downloading {entry_info.get('title', 'Untitled')}: {e}")
        except Exception as e:
            status_placeholder.error(f"An unexpected error occurred for {entry_info.get('title', 'Untitled')}: {e}")

    progress_bar.progress(1.0) # Ensure overall progress reaches 100%
    if st.session_state.downloaded_files:
        status_placeholder.success(f"Playlist download complete. Downloaded {len(st.session_state.downloaded_files)} out of {total_videos} videos.")
    else:
        status_placeholder.warning("No files were successfully downloaded from the playlist.")


# --- Streamlit App Layout ---
st.set_page_config(page_title="YouTube Downloader", page_icon="⬇️", layout="centered")

st.title("⬇️ YouTube Downloader")

# Input for YouTube URL
video_url = st.text_input("Enter YouTube Video or Playlist URL:")

# Session state to store content info (video or playlist) and downloaded files
if 'content_info' not in st.session_state:
    st.session_state.content_info = None
if 'is_playlist' not in st.session_state:
    st.session_state.is_playlist = False
if 'playlist_entries' not in st.session_state:
    st.session_state.playlist_entries = []
if 'downloaded_files' not in st.session_state: # This will now be a list of downloaded file paths
    st.session_state.downloaded_files = []

if video_url:
    # Fetch content info if not already cached/fetched for this URL
    # Use content_info.get('webpage_url') as a unique identifier for the cached entry
    if st.session_state.content_info is None or st.session_state.content_info.get('webpage_url') != video_url:
        st.session_state.content_info, st.session_state.is_playlist, st.session_state.playlist_entries = get_content_info(video_url)

    if st.session_state.content_info:
        info = st.session_state.content_info

        if st.session_state.is_playlist:
            st.subheader(f"Playlist Title: {info.get('title', 'N/A')}")
            st.write(f"Number of videos: {len(st.session_state.playlist_entries)}")
            if 'thumbnail' in info:
                st.image(info['thumbnail'], caption="Playlist Thumbnail", width=200) # Smaller thumbnail for playlist

            # Option to download entire playlist or select specific videos
            download_scope = st.radio(
                "Download Scope:",
                ("Download Entire Playlist", "Select Specific Videos"),
                index=0, # Default to downloading entire playlist
                key='download_scope'
            )

            selected_videos_for_download = []
            if download_scope == "Select Specific Videos":
                st.subheader("Select Videos to Download:")
                for i, entry in enumerate(st.session_state.playlist_entries):
                    if entry: # Ensure entry is not None
                        # Use video ID for unique key if available, else index
                        if st.checkbox(f"{i+1}. {entry.get('title', 'Untitled Video')}", key=f'video_select_{entry.get("id", i)}'):
                            selected_videos_for_download.append(entry)
                if not selected_videos_for_download:
                    st.warning("Please select at least one video from the playlist to enable download options.")
                    # Do not st.stop(), just prevent showing download options/button
            else: # Download Entire Playlist
                selected_videos_for_download = st.session_state.playlist_entries
            
            # This check is crucial to ensure we have content to generate options for
            # before attempting to generate download options.
            first_valid_entry_for_formats = next((e for e in selected_videos_for_download if e is not None), None)

            if not first_valid_entry_for_formats:
                if selected_videos_for_download: # Some videos selected, but none are valid for formats
                     st.warning("Could not retrieve format information for selected videos. They might be unavailable or private.")
                elif st.session_state.is_playlist and not st.session_state.playlist_entries and not st.session_state.content_info.get('formats'):
                     st.warning("No valid videos found in this playlist. It might be empty, all videos are unavailable, or information could not be retrieved.")
                # No st.stop(), allow the app to render. Download button will not appear if no options.
            else:
                st.write("---") # Separator
                st.subheader("Download Options for Selected Videos:")
                output_type = st.radio(
                    "Select Final Output Type:",
                    ('mp4', 'mp3'),
                    index=0,
                    key='playlist_output_type'
                )
                download_options = generate_download_options(first_valid_entry_for_formats, output_type)
                
                if not download_options:
                    st.warning("No suitable download formats found for the selected output type for these videos.")
                    # No st.stop(), allow the app to render. Download button will not appear.
                else:
                    selected_label = st.selectbox(
                        "Select Quality/Stream:",
                        options=[opt['label'] for opt in download_options],
                        index=0,
                        key='playlist_selected_format_label'
                    )
                    selected_option = next(opt for opt in download_options if opt['label'] == selected_label)

                    if st.button("🚀 Start Download Selected Videos"):
                        st.session_state.downloaded_files = [] # Reset list of downloaded files
                        status_placeholder = st.empty()
                        progress_bar = st.progress(0)
                        # Call the new playlist download function
                        download_content_for_playlist(selected_videos_for_download, selected_option, status_placeholder, progress_bar)


        else: # Single video mode
            st.subheader(f"Video Title: {info.get('title', 'N/A')}")
            # Corrected usage of st.image parameter for width
            if 'thumbnail' in info:
                st.image(info['thumbnail'], caption="Video Thumbnail", use_container_width=True)

            output_type = st.radio(
                "Select Final Output Type:",
                ('mp4', 'mp3'),
                index=0,
                key='single_video_output_type'
            )
            download_options = generate_download_options(info, output_type)
            
            if not download_options:
                st.warning("No suitable download formats found for the selected output type for this content. It might be unavailable or private.")
                # Removed st.stop(), allow app to continue
            else:
                selected_label = st.selectbox(
                    "Select Quality/Stream:",
                    options=[opt['label'] for opt in download_options],
                    index=0,
                    key='single_video_selected_format_label'
                )
                selected_option = next(opt for opt in download_options if opt['label'] == selected_label)

                if st.button("🚀 Start Download"):
                    st.session_state.downloaded_files = [] # Reset list for single video
                    status_placeholder = st.empty()
                    progress_bar = st.progress(0)
                    # Call original download_content for a single video
                    download_content(video_url, selected_option, info, status_placeholder, progress_bar)

    else:
        st.warning("Please enter a valid YouTube video or playlist URL.")

# Display download buttons for all downloaded files in session state
if st.session_state.downloaded_files:
    st.subheader("Downloaded Files:")
    for file_path in st.session_state.downloaded_files:
        if os.path.exists(file_path):
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as file:
                st.download_button(
                    label=f"⬇️ {file_name}",
                    data=file,
                    file_name=file_name,
                    mime=f"application/octet-stream",
                    key=f'download_button_{file_path}' # Use file_path as key for uniqueness
                )
        else:
            st.warning(f"File not found on disk: {os.path.basename(file_path)}")

# Sidebar for utility actions and info
st.sidebar.title("Maintenance")
if st.sidebar.button("Clean Temporary Downloads"):
    clean_temp_dir()
    st.session_state.downloaded_files = [] # Clear download state if temp files are cleaned

st.sidebar.markdown("""
---
**How Quality Works:**
1.  **Info Fetching:** The app uses `yt-dlp` to list *all* available video and audio streams for the given YouTube URL.
2.  **Output Type First:** You now select your desired 'Final Output Type' (MP4 or MP3) *first*.
3.  **Dynamic Quality Selection:** The 'Select Quality/Stream' dropdown dynamically filters and sorts to show only streams relevant to your chosen output type:
    * **MP4:** Shows video formats grouped by extension (MP4, WebM, etc.), with highest quality first within each group. For each 'Video Only' stream, a corresponding 'Video + Audio (Merged)' option will also appear. Selecting this will tell the app to download the chosen video stream and merge it with the best available audio stream using `ffmpeg`.
    * **MP3:** Shows audio formats grouped by extension (MP3, M4A, Opus, etc.), with highest bitrate first within each group.
4.  **Download & Conversion:** After selecting your stream and output type, the app downloads the chosen stream(s) and uses `ffmpeg` for post-processing (merging for MP4, converting to MP3).

**Disclaimer:** This tool is for educational purposes only. Please respect copyright laws and YouTube's Terms of Service.
""")
