import streamlit as st
import yt_dlp
import os
import shutil
import tempfile
import re
import time

# --- Configuration ---
TEMP_DIR = "temp_downloads"
MAX_FILE_SIZE_MB = 500

# --- Helper Functions ---
def create_temp_dir():
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)

def clean_temp_dir():
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
            st.toast("Cleaned up temporary files!", icon="🧹")
            os.makedirs(TEMP_DIR)
        except OSError as e:
            st.warning(f"Error cleaning up temp directory: {e}")
    else:
        os.makedirs(TEMP_DIR)

# Ensure temp directory exists at app startup
create_temp_dir()

def get_video_info_and_formats(url):
    try:
        ydl_opts = {
            'noplaylist': True,
            'quiet': True,
            'skip_download': True,
            'format': 'all',
            'force_generic_extractor': True,
            'retries': 3,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                st.error("No information found for this URL.")
                return None, None, None, None

            title = info.get('title', 'Unknown Title')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration')
            
            available_formats = []
            if 'formats' in info:
                for f in info['formats']:
                    format_id = f.get('format_id')
                    ext = f.get('ext')
                    acodec = f.get('acodec')
                    vcodec = f.get('vcodec')
                    format_note = f.get('format_note', '')
                    resolution = f.get('resolution')
                    
                    description_parts = []
                    
                    if resolution and resolution != "audio only":
                        description_parts.append(resolution)
                    
                    if vcodec and vcodec != "none":
                        description_parts.append(vcodec)
                    
                    abr_display = "N/A"
                    abr_val = 0
                    if f.get('abr') is not None and acodec != "none":
                        try:
                            abr_val = int(f['abr'])
                            abr_display = f"{abr_val}kbps"
                        except (ValueError, TypeError):
                            pass 

                    if acodec and acodec != "none":
                        description_parts.append(f"{acodec} {abr_display}")
                    
                    if format_note:
                        description_parts.append(f"({format_note})")
                    
                    tbr_val = 0
                    if f.get('tbr') is not None:
                        try:
                            tbr_val = int(f['tbr'])
                        except (ValueError, TypeError):
                            pass

                    if description_parts and format_id:
                        full_description = f"{format_id}: {ext} - {' '.join(description_parts)}"
                        available_formats.append({
                            'format_id': format_id,
                            'ext': ext,
                            'description': full_description,
                            'vcodec': vcodec,
                            'acodec': acodec,
                            'resolution': resolution,
                            'abr': abr_val,
                            'tbr': tbr_val,
                            'filesize': f.get('filesize', f.get('filesize_approx')), # Include filesize for decision
                        })
            
            def get_res_height(res_str):
                if res_str and 'x' in res_str:
                    try:
                        return int(res_str.split('x')[1])
                    except ValueError:
                        pass
                return 0

            # Sorting all formats initially for consistent internal data,
            # then filtering for display
            available_formats.sort(key=lambda x: (
                get_res_height(x.get('resolution')),
                x.get('abr', 0),
                x.get('tbr', 0)
            ), reverse=True)

            return title, thumbnail, duration, available_formats
    except yt_dlp.utils.DownloadError as e:
        st.error(f"Error fetching video info: {e}. This might be due to geo-restrictions, private video, or YouTube changes.")
        return None, None, None, None
    except Exception as e:
        st.error(f"An unexpected error occurred while processing video info: {e}. Please try a different URL.")
        st.exception(e)
        return None, None, None, None

def download_file(url, format_id, final_output_type, progress_bar, status_text, title_prefix=""):
    create_temp_dir()

    safe_title_prefix = re.sub(r'[\\/:*?"<>|]', '', title_prefix).strip()
    if not safe_title_prefix:
        safe_title_prefix = "download"

    output_filename_template = os.path.join(TEMP_DIR, f"{safe_title_prefix}_%(format_id)s.%(ext)s")
    
    final_filepath = None

    def hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            if total_bytes and total_bytes > 0:
                progress = int((downloaded_bytes / total_bytes) * 100)
                progress_bar.progress(progress)
                status_text.text(f"Downloading: {d['_percent_str']} of {d['_total_bytes_str']} at {d['_speed_str']}")
            else:
                status_text.text(f"Downloading: {d['_speed_str']} ({d['elapsed_str']} elapsed)")
        elif d['status'] == 'finished':
            progress_bar.progress(100)
            status_text.text("Download complete. Processing...")
        elif d['status'] == 'postprocessing':
            status_text.text(f"Post-processing: {d.get('info_dict', {}).get('postprocess_info', '...')}")

    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': output_filename_template,
            'progress_hooks': [hook],
            'external_downloader_args': ['-loglevel', 'error'],
            # --- FFMPEG LOCATION FIX START ---
            # IMPORTANT: Hardcoded path based on your specific input: C:\Users\admin\Documents\ffmpeg\bin
            # Using a raw string (r'') for Windows paths to handle backslashes correctly.
            'ffmpeg_location': r'C:\Users\admin\Documents\ffmpeg\bin\ffmpeg.exe', 
            # --- FFMPEG LOCATION FIX END ---
            'retries': 3,
        }

        if final_output_type == "mp3":
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320', # Highest quality for MP3
            }]
            ydl_opts['extract_audio'] = True
        elif final_output_type == "mp4":
            ydl_opts['merge_output_format'] = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Determine the final downloaded file path
            if 'filepath' in info:
                final_filepath = info['filepath']
            elif 'requested_downloads' in info and len(info['requested_downloads']) > 0:
                # For cases where multiple files are downloaded and merged, yt-dlp might put path in last requested_download
                final_filepath = info['requested_downloads'][-1]['filepath']
            else:
                # Fallback: Search in the temp directory for the expected file extension
                expected_ext = 'mp3' if final_output_type == 'mp3' else 'mp4'
                for f_name in os.listdir(TEMP_DIR):
                    if f_name.startswith(safe_title_prefix) and f_name.endswith(f".{expected_ext}"):
                        final_filepath = os.path.join(TEMP_DIR, f_name)
                        break
                if not final_filepath:
                    raise FileNotFoundError("Could not reliably determine the final downloaded file path.")

            if not os.path.exists(final_filepath):
                raise FileNotFoundError(f"Final file not found on disk: {final_filepath}")

            status_text.success("Processing complete!")
            return final_filepath

    except yt_dlp.utils.DownloadError as e:
        status_text.error(f"Download Error: {e}. This might be due to geo-restrictions, private video, YouTube changes, or issues with the selected format.")
        st.exception(e) # Show full traceback in console for debugging
        return None
    except FileNotFoundError as e:
        status_text.error(f"File System Error: {e}")
        st.exception(e)
        return None
    except Exception as e:
        status_text.error(f"An unexpected error occurred during download/conversion: {e}")
        st.exception(e)
        return None

# --- Streamlit UI Layout ---

st.set_page_config(
    page_title="YouTube Converter",
    page_icon="⬇️",
    layout="centered"
)

st.title("⬇️ YouTube to MP3/MP4 Converter")
st.markdown("Enter a YouTube video URL below to download it in your preferred format and quality.")

youtube_url = st.text_input("Enter YouTube Video URL:", "")

# Initialize session state variables if they don't exist
if 'video_info' not in st.session_state:
    st.session_state.video_info = None
if 'formats' not in st.session_state:
    st.session_state.formats = None
if 'selected_format_id' not in st.session_state:
    st.session_state.selected_format_id = None
if 'final_output_type_radio' not in st.session_state:
    st.session_state.final_output_type_radio = "mp4" # Default to mp4
if 'download_started' not in st.session_state:
    st.session_state.download_started = False
if 'downloaded_file' not in st.session_state:
    st.session_state.downloaded_file = None


# Fetch video info only if URL changes or no info is present
if youtube_url and (st.session_state.video_info is None or st.session_state.video_info.get('url') != youtube_url):
    # Reset states when a new URL is entered
    st.session_state.download_started = False
    st.session_state.downloaded_file = None
    st.session_state.video_info = None
    st.session_state.formats = None
    st.session_state.selected_format_id = None
    
    with st.spinner("Fetching video information... This may take a moment."):
        title, thumbnail, duration, formats = get_video_info_and_formats(youtube_url)
        if title:
            st.session_state.video_info = {'title': title, 'thumbnail': thumbnail, 'duration': duration, 'url': youtube_url}
            st.session_state.formats = formats
            # Reset selected_format_id after new info fetch, it will be set by the dynamic selectbox logic
            st.session_state.selected_format_id = None
        else:
            st.session_state.video_info = None
            st.session_state.formats = None
            st.session_state.selected_format_id = None


# Display video info and options if info is available
if st.session_state.video_info:
    title = st.session_state.video_info['title']
    thumbnail = st.session_state.video_info['thumbnail']
    duration = st.session_state.video_info['duration']
    all_formats = st.session_state.formats # Use all_formats to avoid confusion

    st.subheader("Video Information:")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.image(thumbnail, caption="Video Thumbnail", use_column_width=True)
    with col2:
        st.write(f"**Title:** {title}")
        if duration:
            mins, secs = divmod(duration, 60)
            st.write(f"**Duration:** {int(mins)}m {int(secs)}s")
        
    st.write("---")
    
    st.subheader("Choose Download Quality and Output Type:")

    # --- Radio button for final output type (MP4 or MP3) ---
    st.session_state.final_output_type_radio = st.radio(
        "Final Output Type:",
        ("mp4", "mp3"),
        index=0 if st.session_state.final_output_type_radio == "mp4" else 1, # Set initial state
        horizontal=True,
        key='output_type_radio',
        help="Choose 'MP4' for a video file or 'MP3' to extract and convert the audio portion."
    )

    # --- Dynamic Quality/Stream Selection based on Output Type ---
    format_display_options = [] # This will hold strings for the selectbox
    format_id_map = {} # Maps display string back to format_id

    if all_formats:
        if st.session_state.final_output_type_radio == "mp4":
            # Filter for MP4: Prioritize combined video+audio, then video-only (which yt-dlp can merge)
            mp4_eligible_formats = []
            
            combined_video_audio = [f for f in all_formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            video_only = [f for f in all_formats if f.get('vcodec') != 'none' and f.get('acodec') == 'none']
            
            # Sort combined by resolution (height), then total bitrate
            combined_video_audio.sort(key=lambda x: (
                int(x['resolution'].split('x')[1]) if x.get('resolution') and 'x' in x['resolution'] else 0,
                x.get('tbr', 0)
            ), reverse=True)
            
            # Sort video-only by resolution
            video_only.sort(key=lambda x: (
                int(x['resolution'].split('x')[1]) if x.get('resolution') and 'x' in x['resolution'] else 0
            ), reverse=True)
            
            # Add combined formats first
            for f in combined_video_audio:
                mp4_eligible_formats.append(f)
            # Then add video-only formats
            for f in video_only:
                mp4_eligible_formats.append(f)

            if mp4_eligible_formats:
                st.markdown("**Available MP4 Qualities (Video + Audio or Video Only):**")
                for f in mp4_eligible_formats:
                    # Add filesize to display if available
                    display_str = f"{f['description']}"
                    if f.get('filesize') is not None:
                         display_str += f" ({f['filesize'] / (1024*1024):.2f}MB)"
                    format_display_options.append(display_str)
                    format_id_map[display_str] = f['format_id']
            else:
                st.warning("No suitable video formats found for MP4 output. Try another URL.")

        elif st.session_state.final_output_type_radio == "mp3":
            # Filter for MP3: Consider all formats that have an audio codec
            mp3_eligible_formats = [f for f in all_formats if f.get('acodec') != 'none']
            
            # Sort audio formats by bitrate (abr)
            mp3_eligible_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)

            if mp3_eligible_formats:
                st.markdown("**Available MP3 Qualities (Audio Streams):**")
                for f in mp3_eligible_formats:
                    # Add filesize to display if available
                    display_str = f"{f['description']}"
                    if f.get('filesize') is not None:
                         display_str += f" ({f['filesize'] / (1024*1024):.2f}MB)"
                    format_display_options.append(display_str)
                    format_id_map[display_str] = f['format_id']
            else:
                st.warning("No suitable audio formats found for MP3 output. Try another URL.")
    
    if not format_display_options:
        st.error("No downloadable formats available based on your current selection. Please try another output type or URL.")
        st.session_state.selected_format_id = None # Clear selected if no options
    else:
        # Determine initial selection for the selectbox
        initial_selectbox_index = 0
        if st.session_state.selected_format_id:
            try:
                # Find the current display string for the previously selected format_id
                current_display_str = next(
                    d_str for d_str, f_id in format_id_map.items() 
                    if f_id == st.session_state.selected_format_id
                )
                initial_selectbox_index = format_display_options.index(current_display_str)
            except (StopIteration, ValueError):
                # Previous selection not found in the new filtered list, default to first
                st.session_state.selected_format_id = None 
                initial_selectbox_index = 0
        
        # If after checking, selected_format_id is still None, pick the first one from the new list
        if st.session_state.selected_format_id is None and format_display_options:
            st.session_state.selected_format_id = format_id_map.get(format_display_options[0])

        selected_display_option = st.selectbox(
            "Select Quality/Stream:",
            format_display_options,
            index=initial_selectbox_index,
            key='quality_selectbox', # Ensure key is stable
            help="Choose the desired quality stream. The list updates based on your 'Final Output Type' selection."
        )
        
        # Update selected_format_id based on current selectbox choice
        st.session_state.selected_format_id = format_id_map.get(selected_display_option)

        if st.session_state.selected_format_id:
            st.info(f"Selected stream: `{st.session_state.selected_format_id}` for `{st.session_state.final_output_type_radio.upper()}` conversion.")

            if st.button(f"Download as {st.session_state.final_output_type_radio.upper()}"):
                st.session_state.downloaded_file = None # Clear previous download
                st.session_state.download_started = True

                st.write("Starting download...")
                progress_bar = st.progress(0)
                status_text = st.empty()

                clean_temp_dir() # Ensure clean slate for new download

                downloaded_file = download_file(
                    youtube_url,
                    st.session_state.selected_format_id,
                    st.session_state.final_output_type_radio,
                    progress_bar,
                    status_text,
                    title_prefix=title # Pass title for filename
                )
                
                if downloaded_file and os.path.exists(downloaded_file):
                    st.session_state.downloaded_file = downloaded_file
                    
                    file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                    st.success(f"File ready: {os.path.basename(downloaded_file)} ({file_size_mb:.2f} MB)")

                    with open(downloaded_file, "rb") as file:
                        if file_size_mb <= MAX_FILE_SIZE_MB:
                            st.download_button(
                                label=f"Click to Download {os.path.basename(downloaded_file)}",
                                data=file,
                                file_name=os.path.basename(downloaded_file),
                                mime="video/mp4" if st.session_state.final_output_type_radio == "mp4" else "audio/mpeg",
                                key=downloaded_file # Use a unique key for the button to reset it
                            )
                        else:
                            st.warning(f"File size ({file_size_mb:.2f} MB) exceeds direct download limit ({MAX_FILE_SIZE_MB} MB).")
                            st.info("For very large files, direct download via Streamlit's button might fail or be slow. The file is saved on the server's disk in the 'temp_downloads' directory.")
                    
                    # Give Streamlit a moment to process the download button click before potentially cleaning up.
                    time.sleep(1) 
                    st.info("The downloaded file is stored temporarily and will be removed soon.")
                    
                else:
                    st.error("Failed to download or convert the video. Please check the console/logs for details.")
                    st.session_state.downloaded_file = None
        else:
            st.warning("Please select a quality/stream before downloading.")

else:
    if youtube_url:
        pass # Error messages handled by get_video_info_and_formats (e.g., "No information found")

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
3.  **Dynamic Quality Selection:** The 'Select Quality/Stream' dropdown dynamically filters to show only streams relevant to your chosen output type:
    * **MP4:** Primarily shows streams with both video and audio. If none are available, it will show video-only streams (which `yt-dlp` will try to merge with the best available audio).
    * **MP3:** Shows streams that contain audio (either audio-only or video+audio streams, as audio can be extracted from both).
4.  **Download & Conversion:** After selecting your stream and output type, the app downloads the chosen stream and uses `ffmpeg` for post-processing (merging for MP4, converting to MP3).

**Disclaimer:** This tool is for educational purposes only. Please respect copyright laws and YouTube's Terms of Service.
""")