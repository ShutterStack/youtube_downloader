import streamlit as st
import yt_dlp
import os
import shutil
import tempfile
import re
import time
import glob # Import glob for file searching

# --- Configuration ---
TEMP_DIR = "temporary_downloads"
MAX_FILE_SIZE_MB = 500
# Ensure ffmpeg_location is correctly set for your system
# IMPORTANT: Adjust this path if your ffmpeg.exe is located elsewhere!
# On Windows, it should point directly to ffmpeg.exe
# On Linux/macOS, it's usually just 'ffmpeg' if it's in your PATH, or a full path like '/usr/bin/ffmpeg'
FFMPEG_LOCATION = r'C:\Users\admin\Documents\ffmpeg\bin\ffmpeg.exe' # Adjusted for Windows based on your logs


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
    # Also remove any characters that might cause issues with pathing or globbing if they appear unexpectedly
    # For robust matching, we might also replace spaces with underscores or similar if exact matches are needed,
    # but for simple globbing, spaces are usually fine.
    # Replace sequences of dots at the end (common issue with some filenames)
    cleaned_filename = re.sub(r'\.+$', '', cleaned_filename)
    return cleaned_filename.strip() # Remove leading/trailing whitespace

# Cache video info to avoid re-fetching on every rerun
@st.cache_data(show_spinner="Fetching video information...")
def get_video_info_and_formats(url):
    try:
        ydl_opts = {
            'noplaylist': True,
            'quiet': True,
            'skip_download': True,
            'format': 'all', # Get all formats to allow flexible selection
            'force_generic_extractor': True,
            'retries': 3,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None, None
            return info, ydl.sanitize_info(info) # Return sanitized info for easier processing
    except yt_dlp.utils.DownloadError as e:
        st.error(f"Error fetching video info: {e}")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return None, None


# Function to dynamically generate download options based on desired output type
def generate_download_options(info, output_type):
    options = []
    
    # Sort formats by quality (higher resolution first, then higher fps)
    formats = sorted(info['formats'], key=lambda f: (
        f.get('height') or 0, 
        f.get('fps') or 0, 
        f.get('tbr') or 0 # Total bitrate
    ), reverse=True)

    if output_type == 'mp4':
        # Add "Video + Audio (Merged)" options for MP4 output
        # We need distinct options for different video qualities + best audio
        merged_video_qualities = set()
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('ext') == 'mp4' and f.get('height') and f.get('height') not in merged_video_qualities:
                # Add an option for this video quality merged with best audio
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
        
        # Add a general "Best Video + Best Audio (Merged MP4 - Recommended)" option
        options.insert(0, {
            'label': 'Best Video + Best Audio (Merged MP4 - Recommended)',
            'format_id': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio', # Prioritize mp4+m4a, fallback to any best
            'is_merged': True,
            'ext': 'mp4', # Explicitly set expected output extension
            'vcodec': 'best',
            'acodec': 'aac (re-encoded)',
            'resolution': 'best'
        })
        
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
        # Add "Audio Only" options for MP3 output
        for f in formats:
            if f.get('acodec') != 'none': # Check if it has an audio codec
                label = f"Audio Only ({f.get('acodec', '')}, {f.get('abr', 0)}kbps)"
                options.append({
                    'label': label,
                    'format_id': f['format_id'],
                    'is_merged': False, # Even if it's bestaudio, it's not merged video+audio
                    'ext': 'mp3', # Explicitly set expected output extension (due to postprocessor)
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec'),
                    'resolution': f.get('resolution')
                })
    
    return options

# Global variable to store the final downloaded file path from yt-dlp's hooks
# This is a fallback debugging print, not the primary method anymore
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


# Function to download the selected content
def download_content(url, selected_option, info, status_placeholder, progress_bar):
    global download_complete_filepath_from_hook
    download_complete_filepath_from_hook = None # Reset at the start of each download

    try:
        sanitized_title = sanitize_filename(info.get('title', 'video'))
        
        # Determine the output filename template based on whether it's a merge
        if selected_option['is_merged']:
            # For merged files, the final name will often be without format_id
            output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}.%(ext)s")
        else:
            # For single formats, include format_id for uniqueness as yt-dlp often does
            output_filename_template = os.path.join(TEMP_DIR, f"{sanitized_title}_%(format_id)s.%(ext)s")

        ydl_opts = {
            'outtmpl': output_filename_template,
            'progress_hooks': [lambda d: update_progress(d, status_placeholder, progress_bar)],
            'ffmpeg_location': FFMPEG_LOCATION,
            'retries': 3,
            'verbose': True,
            'compat_opts': set(),
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.74 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            }
        }

        # Configure based on output type and whether it's a merged option
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
            # Execute the download. Hooks will run during this process.
            download_result = ydl.download([url])
            
            # --- Robust File Path Discovery ---
            final_downloaded_path_to_check = None
            
            # Sanitize title again for robust glob matching
            sanitized_title_for_glob = sanitize_filename(info.get('title', 'video'))

            if selected_option['is_merged']:
                # For merged MP4s, the pattern is straightforward (no format ID)
                expected_ext = 'mp4'
                # Use glob to find files matching "title*.mp4"
                matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}*.{expected_ext}"))
                # Filter to prioritize exact match without format_id if it exists, otherwise first match
                exact_match = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                if exact_match in matching_files:
                    final_downloaded_path_to_check = exact_match
                elif matching_files:
                    final_downloaded_path_to_check = matching_files[0] # Take the first match
            else: # Not merged (e.g., MP3 or video-only streams)
                expected_ext = selected_option['ext'] # 'mp3' or 'mp4'/'webm' for video-only
                # For non-merged, yt-dlp usually includes the format_id (e.g., "_140.mp3")
                # So, search for "title_*.ext"
                matching_files = glob.glob(os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}_*.{expected_ext}"))
                if matching_files:
                    # Sort by modification time to get the most recent, if multiple exist
                    final_downloaded_path_to_check = max(matching_files, key=os.path.getmtime)
                else:
                    # Fallback if yt-dlp somehow produces a simple name for non-merged (less common)
                    simple_name_path = os.path.join(TEMP_DIR, f"{sanitized_title_for_glob}.{expected_ext}")
                    if os.path.exists(simple_name_path):
                        final_downloaded_path_to_check = simple_name_path

            print(f"DEBUG: Final path determined by glob search: {final_downloaded_path_to_check}")

            if final_downloaded_path_to_check and os.path.exists(final_downloaded_path_to_check):
                st.session_state.downloaded_file = final_downloaded_path_to_check
                status_placeholder.success(f"Download complete: {os.path.basename(final_downloaded_path_to_check)}")
            else:
                status_placeholder.error(f"Download completed, but file not found at: {final_downloaded_path_to_check}. This may indicate an unexpected filename or an issue with file creation/deletion by yt-dlp/ffmpeg. Please check console for more errors.")

    except yt_dlp.utils.DownloadError as e:
        status_placeholder.error(f"Download Error: {e}")
        st.error("Failed to download. Check the console/logs for details.")
    except Exception as e:
        status_placeholder.error(f"An unexpected error occurred: {e}")
        st.error("Failed to download. Check the console/logs for details.")

# --- Streamlit App Layout ---
st.set_page_config(page_title="YouTube Downloader", page_icon="⬇️", layout="centered")

st.title("⬇️ YouTube Downloader")

# Input for YouTube URL
video_url = st.text_input("Enter YouTube Video URL:")

# Session state to store video info and downloaded file path
if 'video_info' not in st.session_state:
    st.session_state.video_info = None
if 'downloaded_file' not in st.session_state:
    st.session_state.downloaded_file = None

if video_url:
    # Fetch video info if not already cached/fetched for this URL
    if st.session_state.video_info is None or st.session_state.video_info.get('webpage_url') != video_url:
        st.session_state.video_info, _ = get_video_info_and_formats(video_url) # _ for sanitized_info, not used directly here

    if st.session_state.video_info:
        info = st.session_state.video_info
        st.subheader(f"Video Title: {info.get('title', 'N/A')}")
        if 'thumbnail' in info:
            st.image(info['thumbnail'], caption="Video Thumbnail", use_column_width=True)

        # Output Type Selection
        output_type = st.radio(
            "Select Final Output Type:",
            ('mp4', 'mp3'),
            index=0, # Default to MP4
            key='output_type'
        )

        # Dynamically generate and display format options based on selected output type
        download_options = generate_download_options(info, output_type)
        
        if not download_options:
            st.warning("No suitable download formats found for the selected output type.")
        else:
            # Create display labels for the selectbox
            option_labels = [opt['label'] for opt in download_options]
            
            selected_label = st.selectbox(
                "Select Quality/Stream:",
                options=option_labels,
                index=0, # Default to the first option (likely best quality)
                key='selected_format_label'
            )
            
            # Find the full option dictionary based on the selected label
            selected_option = next(opt for opt in download_options if opt['label'] == selected_label)

            st.write(f"Selected: **{selected_option['label']}**")
            st.write(f"Expected Extension: **.{selected_option['ext']}**")

            # Download Button
            if st.button("🚀 Start Download"):
                st.session_state.downloaded_file = None # Reset previous download
                status_placeholder = st.empty()
                progress_bar = st.progress(0)
                download_content(video_url, selected_option, info, status_placeholder, progress_bar)

    else:
        st.warning("Please enter a valid YouTube video URL.")

# Download Button for the file in session state
if st.session_state.downloaded_file and os.path.exists(st.session_state.downloaded_file):
    with open(st.session_state.downloaded_file, "rb") as file:
        st.download_button(
            label="⬇️ Download File",
            data=file,
            file_name=os.path.basename(st.session_state.downloaded_file),
            mime=f"application/octet-stream" # Generic mime type, browser handles extension
        )

# Sidebar for utility actions and info
st.sidebar.title("Maintenance")
if st.sidebar.button("Clean Temporary Downloads"):
    clean_temp_dir()
    st.session_state.downloaded_file = None # Clear download state if temp files are cleaned

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
